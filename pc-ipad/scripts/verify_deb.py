"""Inspect the rootful DEB in memory. This does not test behavior on an iPad."""
import argparse
import contextlib
import hashlib
import io
import json
from pathlib import Path,PurePosixPath
import plistlib
import re
import struct
import tarfile
import zipfile

APP='Applications/ShockStream.app'
HELPER='usr/libexec/shockstream-waked'
DAEMON='Library/LaunchDaemons/com.shock.stream.wake.plist'
PACKAGE='com.shock.stream.ipad'
MAX_ARCHIVE=128*1024*1024
MAX_FILES=4096


def require(value,message):
    if not value:raise ValueError(message)


def ar_members(data):
    require(len(data)<=MAX_ARCHIVE and data.startswith(b'!<arch>\n'),'Invalid or excessive DEB ar archive.')
    result={};offset=8
    while offset<len(data):
        require(offset+60<=len(data),'Truncated ar member header.')
        header=data[offset:offset+60];require(header[58:60]==b'`\n','Invalid ar member header.')
        try:
            name=header[:16].decode('ascii').strip().removesuffix('/')
            raw_size=header[48:58].decode('ascii').strip()
            require(raw_size.isdigit(),'Invalid ar member size.');size=int(raw_size)
        except (UnicodeDecodeError,ValueError) as exc:raise ValueError('Invalid ar member metadata.') from exc
        offset+=60;require(offset+size<=len(data),'Truncated ar member data.')
        require(name in ('debian-binary','control.tar.gz','data.tar.gz') and name not in result,'Unexpected or duplicate DEB member.')
        result[name]=data[offset:offset+size];offset+=size
        if size&1:
            require(offset<len(data) and data[offset:offset+1]==b'\n','Missing ar alignment byte.');offset+=1
    require(list(result)==['debian-binary','control.tar.gz','data.tar.gz'],'DEB must contain standard gzip control/data archives.')
    require(result['debian-binary']==b'2.0\n','Unsupported Debian binary format.')
    return result


def canonical_path(name):
    require(isinstance(name,str) and '\x00' not in name and '\\' not in name,'Invalid tar path.')
    while name.startswith('./'):name=name[2:]
    if name in ('','.'):return ''
    name=name.rstrip('/')
    require(not name.startswith('/') and all(part not in ('','.','..') for part in name.split('/')),'Unsafe tar path.')
    require(str(PurePosixPath(name))==name,'Noncanonical tar path.')
    return name


def tar_members(data):
    require(data.startswith(b'\x1f\x8b'),'gzip compression is required for the legacy bootstrap.')
    result={};total=0
    try:
        with tarfile.open(fileobj=io.BytesIO(data),mode='r:gz') as archive:
            for index,member in enumerate(archive):
                require(index<MAX_FILES,'Too many tar members.')
                path=canonical_path(member.name)
                require(member.isfile() or member.isdir(),'Links and special files are not allowed.')
                require(member.size>=0 and (member.isfile() or member.size==0),'Invalid tar member size.')
                require(member.uid==0 and member.gid==0,'Payload must be owned by root:wheel (0:0).')
                require(not member.mode&0o7022,'Set-id/sticky or group/world-writable package entry.')
                if not path:
                    require(member.isdir() and member.mode&0o777==0o755,'Archive root must be a mode-755 directory.');continue
                require(path not in result,'Duplicate tar path.')
                total+=member.size;require(total<=MAX_ARCHIVE,'Excessive uncompressed package size.')
                body=archive.extractfile(member).read() if member.isfile() else None
                require(body is None or len(body)==member.size,'Truncated tar payload.')
                result[path]=(member,body)
    except (tarfile.TarError,OSError,EOFError) as exc:raise ValueError('Invalid gzip tar archive.') from exc
    return result


def parse_control(body):
    try:text=body.decode('utf-8')
    except UnicodeDecodeError as exc:raise ValueError('Control file must be UTF-8.') from exc
    values={}
    for line in text.splitlines():
        if not line:continue
        require(not line.startswith((' ','\t')) and ':' in line,'Malformed control field.')
        key,value=line.split(':',1);require(key not in values,'Duplicate control field.');values[key]=value.strip()
    return values


def verify_macho(binary,description):
    """Check native helper ABI and all executable code pages signed by ldid."""
    require(len(binary)>=28,description+': truncated Mach-O.')
    magic,cpu,subtype,kind,count,total,_=struct.unpack_from('<7I',binary)
    require(magic==0xfeedface and cpu==12 and subtype&0xffffff==9 and kind==2,description+': ARMv7 executable required.')
    require(count<=1024 and 28+total<=len(binary),description+': invalid load-command range.')
    offset=28;signature=None;minimum=None
    for _ in range(count):
        require(offset+8<=28+total,description+': truncated load command.')
        command,size=struct.unpack_from('<II',binary,offset)
        require(size>=8 and size%4==0 and offset+size<=28+total,description+': invalid load command.')
        if command in (0x25,0x1d):
            require(size>=16,description+': truncated version/signature command.')
            if command==0x25:minimum=struct.unpack_from('<I',binary,offset+8)[0]
            else:
                require(signature is None,description+': duplicate code signature.')
                signature=struct.unpack_from('<II',binary,offset+8)
        offset+=size
    require(offset==28+total and minimum==0x90000,description+': deployment target must be iOS 9.0.')
    require(signature is not None,description+': embedded signature required.')
    sig_offset,sig_size=signature
    require(sig_offset>=offset and sig_size>=12 and sig_offset+sig_size<=len(binary),description+': invalid signature range.')
    blob=binary[sig_offset:sig_offset+sig_size]
    sig_magic,length,slots_count=struct.unpack_from('>III',blob)
    require(sig_magic==0xfade0cc0 and length<=len(blob) and 12+slots_count*8<=length,description+': invalid signature superblob.')
    valid=False
    for index in range(slots_count):
        slot,where=struct.unpack_from('>II',blob,12+index*8)
        require(slot!=0x10000,description+': expected ldid signature without Apple CMS provisioning.')
        require(where>=12+slots_count*8 and where+8<=length,description+': invalid signature slot.')
        child_magic,child_length=struct.unpack_from('>II',blob,where)
        require(child_length>=8 and where+child_length<=length,description+': invalid signature child.')
        if slot!=0:continue
        require(not valid and child_magic==0xfade0c02 and child_length>=44,description+': invalid CodeDirectory.')
        directory=blob[where:where+child_length]
        hash_offset,ident,special,code_slots,code_limit=struct.unpack_from('>5I',directory,16)
        hash_size,hash_type,_,page=struct.unpack_from('>4B',directory,36)
        sizes={1:20,2:32,3:20,4:48}
        require(hash_type in sizes and hash_size==sizes[hash_type] and page<=16,description+': unsupported code hash format.')
        require(code_limit==sig_offset and code_slots==(code_limit+(1<<page)-1)//(1<<page),description+': signature must cover the entire executable.')
        require(hash_offset>=44 and hash_offset+code_slots*hash_size<=child_length and hash_offset-special*hash_size>=44,description+': invalid code hash table.')
        require(44<=ident<hash_offset-special*hash_size and b'\0' in directory[ident:hash_offset-special*hash_size],description+': missing code identifier.')
        hasher={1:hashlib.sha1,2:hashlib.sha256,3:hashlib.sha256,4:hashlib.sha384}[hash_type]
        for number in range(code_slots):
            begin=number*(1<<page);end=min(begin+(1<<page),code_limit)
            expected=directory[hash_offset+number*hash_size:hash_offset+(number+1)*hash_size]
            require(hasher(binary[begin:end]).digest()[:hash_size]==expected,description+': code signature page hash mismatch.')
        valid=True
    require(valid,description+': CodeDirectory is missing.')
    return dict(architecture='armv7',minimumOS='9.0',signature='ldid CodeDirectory with verified code-page hashes')


def verify(path,version='0.4.0',build=None):
    from verify_ipa import verify as verify_ipa
    path=Path(path);raw=path.read_bytes();members=ar_members(raw)
    control=tar_members(members['control.tar.gz']);data=tar_members(members['data.tar.gz'])
    require(set(control)=={'control','preinst','postinst','prerm','postrm'},'Unexpected or missing control archive files.')
    for name,(entry,body) in control.items():
        require(entry.isfile() and entry.mode&0o777==(0o644 if name=='control' else 0o755),'Incorrect control file permissions.')
        if name!='control':require(body.startswith(b'#!/bin/sh\n') and b'\r' not in body,'Scripts must use POSIX sh and LF endings.')
    metadata=parse_control(control['control'][1])
    require(metadata.get('Package')==PACKAGE and metadata.get('Architecture')=='iphoneos-arm','Incorrect package identifier or architecture.')
    match=re.fullmatch(r'(\d+\.\d+\.\d+)-(\d+)',metadata.get('Version',''))
    require(match is not None and match.group(1)==version and int(match.group(2))>=1,'Incorrect package version.')
    if build is not None:require(int(match.group(2))==int(build),'Incorrect package build.')
    build=match.group(2)
    dependencies={value.strip() for value in metadata.get('Depends','').split(',')}
    require({'firmware (>= 9.0)','firmware (<< 10.0)','uikittools'}<=dependencies,'Missing legacy iOS 9 dependencies.')
    allowed_dirs={'Applications',APP,'usr','usr/libexec','Library','Library/LaunchDaemons'}
    require(allowed_dirs<=set(data),'Required payload directories are missing.')
    for name,(entry,body) in data.items():
        require(name in allowed_dirs or name.startswith(APP+'/') or name in (HELPER,DAEMON),'Unexpected payload path: '+name)
        if name in allowed_dirs:require(entry.isdir(),'Payload directory is a regular file: '+name)
        for parent in PurePosixPath(name).parents:
            parent=str(parent)
            if parent in data:require(data[parent][0].isdir(),'Payload has a file as an ancestor: '+parent)
        require((entry.isdir() and entry.mode&0o777==0o755) or
                (entry.isfile() and entry.mode&0o777==(0o755 if name in (APP+'/ShockStream',HELPER) else 0o644)),
                'Incorrect payload permissions: '+name)
    for name in (APP+'/Info.plist',APP+'/ShockStream',APP+'/.shock-deb',HELPER,DAEMON):
        require(name in data and data[name][0].isfile(),'Missing payload file: '+name)
    info=plistlib.loads(data[APP+'/Info.plist'][1])
    require(info.get('CFBundleIdentifier')==PACKAGE and info.get('CFBundleExecutable')=='ShockStream','Incorrect app bundle identity.')
    require(info.get('CFBundleShortVersionString')==version and str(info.get('CFBundleVersion'))==build,'App version/build differs from DEB.')
    marker=json.loads(data[APP+'/.shock-deb'][1])
    require(marker==dict(package=PACKAGE,version=version,build=build,architecture='iphoneos-arm'),'Invalid DEB app marker.')
    daemon=plistlib.loads(data[DAEMON][1])
    require(daemon.get('Label')=='com.shock.stream.wake' and daemon.get('ProgramArguments')==['/'+HELPER],'Incorrect daemon label/program.')
    require(daemon.get('UserName')=='mobile' and daemon.get('GroupName','mobile')=='mobile','Daemon must run as mobile.')
    require(daemon.get('RunAtLoad') is True and daemon.get('KeepAlive') is True,'Daemon startup/restart configuration missing.')
    throttle=daemon.get('ThrottleInterval')
    require(isinstance(throttle,int) and not isinstance(throttle,bool) and throttle>=5,'Daemon restart throttling missing.')
    environment=daemon.get('EnvironmentVariables',{})
    require(environment.get('HOME')=='/var/mobile' and environment.get('CFFIXED_USER_HOME','/var/mobile')=='/var/mobile','Daemon must use mobile HOME.')
    require('Sockets' not in daemon,'Helper manages its own loopback listener; launchd must not expose a socket.')
    app_binary=data[APP+'/ShockStream'][1];verify_macho(app_binary,'Application')
    helper_result=verify_macho(data[HELPER][1],'Wake helper')
    # Reuse existing app checks for required media frameworks, metadata and signature.
    memory=io.BytesIO()
    with zipfile.ZipFile(memory,'w') as archive:
        archive.writestr('Payload/ShockStream.app/Info.plist',data[APP+'/Info.plist'][1])
        archive.writestr('Payload/ShockStream.app/ShockStream',app_binary)
    memory.seek(0)
    with contextlib.redirect_stdout(io.StringIO()):app_result=verify_ipa(memory)
    return dict(package=PACKAGE,version=metadata['Version'],architecture='iphoneos-arm',application=app_result,
                wakeHelper=helper_result,launchUser='mobile',payloadFiles=sum(entry.isfile() for entry,_ in data.values()),
                sha256=hashlib.sha256(raw).hexdigest(),
                validation='Archive, paths, permissions, launchd metadata and signed ARMv7 code checked; physical iPad behavior not tested.')


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('path',type=Path)
    parser.add_argument('--version',default='0.4.0');parser.add_argument('--build',type=int)
    args=parser.parse_args();print(json.dumps(verify(args.path,args.version,args.build),indent=2))


if __name__=='__main__':main()
