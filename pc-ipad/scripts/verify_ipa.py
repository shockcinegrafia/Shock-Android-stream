"""Verify actual IPA contents, ARMv7 Mach-O target and embedded ad-hoc signature."""
import json
import plistlib
from pathlib import Path
import struct
import sys
import zipfile

def verify(path):
    with zipfile.ZipFile(path) as archive:
        plist_names=[n for n in archive.namelist() if n.startswith('Payload/') and n.count('/')==2 and n.endswith('/Info.plist')]
        assert len(plist_names)==1,'one application required'
        plist_name=plist_names[0];info=plistlib.loads(archive.read(plist_name))
        assert info['CFBundleIdentifier']=='com.shock.stream.ipad'
        assert info['MinimumOSVersion']=='9.0'
        binary=archive.read(plist_name.rsplit('/',1)[0]+'/'+info['CFBundleExecutable'])
        header=struct.unpack_from('<7I',binary)
        magic,cpu,subtype,kind,commands,total,flags=header
        assert magic==0xfeedface,'32-bit Mach-O required'
        assert cpu==12 and subtype&0xffffff==9,'ARMv7 required'
        assert kind==2,'executable required'
        offset=28;signature=None;minimum=None;libraries=[]
        for _ in range(commands):
            command,size=struct.unpack_from('<II',binary,offset)
            assert size>=8 and offset+size<=len(binary)
            if command==0x25:minimum=struct.unpack_from('<I',binary,offset+8)[0]
            if command==0x1d:signature=struct.unpack_from('<II',binary,offset+8)
            if command in (0xc,0x80000018):
                name=struct.unpack_from('<I',binary,offset+8)[0]
                libraries.append(binary[offset+name:offset+size].split(b'\0')[0].decode())
            offset+=size
        assert minimum==0x90000,'deployment target must be iOS 9.0'
        assert any('VideoToolbox.framework' in name for name in libraries)
        assert any('AudioToolbox.framework' in name for name in libraries)
        assert signature and signature[1]>0,'embedded signature required'
        sig_offset,sig_size=signature
        assert sig_offset+sig_size<=len(binary)
        blob=binary[sig_offset:sig_offset+sig_size]
        sig_magic,length,count=struct.unpack_from('>III',blob)
        assert sig_magic==0xfade0cc0 and length<=len(blob),'signature superblob required'
        ad_hoc=False
        for index in range(count):
            slot,where=struct.unpack_from('>II',blob,12+index*8)
            if slot==0:
                cd_magic,cd_length,version,cd_flags=struct.unpack_from('>IIII',blob,where)
                assert cd_magic==0xfade0c02 and where+cd_length<=len(blob)
                ad_hoc=bool(cd_flags&2)
        assert ad_hoc,'expected ad-hoc jailbreak signature'
        result={'bundle':info['CFBundleIdentifier'],'version':info['CFBundleShortVersionString'],'build':info['CFBundleVersion'],'architecture':'armv7','minimumOS':'9.0','signature':'ad-hoc; requires compatible jailbreak installation','libraries':libraries}
        print(json.dumps(result,indent=2));return result

if __name__=='__main__':verify(Path(sys.argv[1]))
