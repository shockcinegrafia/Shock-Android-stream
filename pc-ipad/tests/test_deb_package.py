"""Independent DEB fixtures and harmless script simulations; no device required."""
import io
import json
import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import package_deb
import verify_deb
from test_signature import signed_binary


def tar_bytes(entries):
    memory=io.BytesIO()
    with tarfile.open(fileobj=memory,mode='w:gz',format=tarfile.USTAR_FORMAT) as archive:
        for name,body,mode,uid,kind in entries:
            item=tarfile.TarInfo(name);item.mode=mode;item.uid=uid;item.gid=0;item.mtime=0;item.type=kind
            if kind==tarfile.SYMTYPE:item.linkname='/etc/passwd'
            if body is not None:item.size=len(body)
            archive.addfile(item,io.BytesIO(body) if body is not None else None)
    return memory.getvalue()


def ar_bytes(members):
    result=bytearray(b'!<arch>\n')
    for name,body in members:
        result.extend(f'{name+"/":<16}{0:<12}{0:<6}{0:<6}{"100644":<8}{len(body):<10}`\n'.encode('ascii'))
        result.extend(body)
        if len(body)&1:result.extend(b'\n')
    return bytes(result)


class DebFixture(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory();self.folder=Path(self.temporary.name)
        self.app=self.folder/'source/ShockStream.app';self.app.mkdir(parents=True)
        info=dict(CFBundleIdentifier=package_deb.PACKAGE,CFBundleExecutable='ShockStream',MinimumOSVersion='9.0',
                  CFBundleShortVersionString='0.4.0',CFBundleVersion='17')
        (self.app/'Info.plist').write_bytes(plistlib.dumps(info));(self.app/'ShockStream').write_bytes(signed_binary())
        (self.app/'Icon-76.png').write_bytes(b'fixture-icon')
        self.helper=self.folder/'helper';self.helper.write_bytes(signed_binary())
        self.plist=self.folder/'launchdaemon.plist'
        daemon=dict(Label='com.shock.stream.wake',ProgramArguments=[package_deb.HELPER],UserName='mobile',GroupName='mobile',
                    RunAtLoad=True,KeepAlive=True,ThrottleInterval=10,
                    EnvironmentVariables=dict(HOME='/var/mobile',CFFIXED_USER_HOME='/var/mobile'))
        self.plist.write_bytes(plistlib.dumps(daemon));self.stage=self.folder/'stage';self.stage.mkdir()
        package_deb.stage_package(self.stage,self.app,self.helper,self.plist,'0.4.0',17)

    def tearDown(self):self.temporary.cleanup()

    def entries(self):
        control=[];data=[]
        for path in sorted(self.stage.rglob('*')):
            relative=path.relative_to(self.stage).as_posix()
            if relative=='DEBIAN':continue
            target=control if relative.startswith('DEBIAN/') else data
            name=relative.removeprefix('DEBIAN/')
            directory=path.is_dir()
            executable=(relative in ('Applications/ShockStream.app/ShockStream',verify_deb.HELPER) or
                        relative.startswith('DEBIAN/') and name!='control')
            mode=0o755 if directory or executable else 0o644
            target.append((name,None if directory else path.read_bytes(),mode,0,tarfile.DIRTYPE if directory else tarfile.REGTYPE))
        return control,data

    def fixture(self,mutate=None):
        control,data=self.entries()
        if mutate:control,data=mutate(control,data)
        path=self.folder/'fixture.deb'
        path.write_bytes(ar_bytes([('debian-binary',b'2.0\n'),('control.tar.gz',tar_bytes(control)),('data.tar.gz',tar_bytes(data))]))
        return path

    def replace(self,name,body=None,mode=None,uid=None,kind=None):
        def mutate(control,data):
            def convert(entry):
                if entry[0]!=name:return entry
                return (name,body if body is not None else entry[1],mode if mode is not None else entry[2],
                        uid if uid is not None else entry[3],kind if kind is not None else entry[4])
            return [convert(e) for e in control],[convert(e) for e in data]
        return mutate


class DebVerificationTests(DebFixture):
    def test_complete_rootful_package_checks_both_signed_executables(self):
        result=verify_deb.verify(self.fixture(),build=17)
        self.assertEqual(result['version'],'0.4.0-17');self.assertEqual(result['launchUser'],'mobile')
        self.assertEqual(result['application']['architecture'],'armv7');self.assertEqual(result['wakeHelper']['minimumOS'],'9.0')
        self.assertIn('not tested',result['validation'])

    def test_archive_truncation_and_duplicate_member_are_rejected(self):
        path=self.fixture();body=path.read_bytes();path.write_bytes(body[:-1])
        with self.assertRaises(ValueError):verify_deb.verify(path)
        with self.assertRaisesRegex(ValueError,'duplicate'):
            verify_deb.ar_members(ar_bytes([('debian-binary',b'2.0\n'),('debian-binary',b'2.0\n')]))

    def test_traversal_symlink_and_unrelated_payload_are_rejected(self):
        for name,kind in (('../outside',tarfile.REGTYPE),('etc/passwd',tarfile.REGTYPE),
                          (verify_deb.APP+'/link',tarfile.SYMTYPE)):
            def mutate(control,data):return control,data+[(name,b'test',0o644,0,kind)]
            with self.subTest(name=name):
                with self.assertRaises(ValueError):verify_deb.verify(self.fixture(mutate))

    def test_permissions_and_ownership_are_verified(self):
        for options in (dict(mode=0o777),dict(uid=501),dict(mode=0o644)):
            with self.subTest(options=options):
                with self.assertRaises(ValueError):verify_deb.verify(self.fixture(self.replace(verify_deb.HELPER,**options)))

    def test_parent_directory_cannot_be_replaced_by_a_file(self):
        with self.assertRaisesRegex(ValueError,'directory is a regular file'):
            verify_deb.verify(self.fixture(self.replace('usr/libexec',body=b'file',mode=0o644,kind=tarfile.REGTYPE)))

    def test_run_as_root_and_externally_configured_socket_are_rejected(self):
        for change in (dict(UserName='root'),dict(Sockets={'listener':{'SockNodeName':'0.0.0.0'}}),dict(ThrottleInterval=0)):
            daemon=plistlib.loads(self.plist.read_bytes());daemon.update(change)
            with self.subTest(change=change):
                with self.assertRaises(ValueError):
                    verify_deb.verify(self.fixture(self.replace(verify_deb.DAEMON,body=plistlib.dumps(daemon))))

    def test_wrong_architecture_version_and_missing_marker_are_rejected(self):
        control=(self.stage/'DEBIAN/control').read_bytes()
        for changed in (control.replace(b'iphoneos-arm',b'iphoneos-arm64'),control.replace(b'0.4.0-17',b'0.4.1-17')):
            with self.assertRaises(ValueError):verify_deb.verify(self.fixture(self.replace('control',body=changed)))
        def no_marker(control,data):return control,[e for e in data if not e[0].endswith('/.shock-deb')]
        with self.assertRaisesRegex(ValueError,'Missing payload'):verify_deb.verify(self.fixture(no_marker))

    def test_helper_code_tampering_and_wrong_abi_are_rejected(self):
        changed=bytearray(signed_binary());changed[2000]^=1
        with self.assertRaisesRegex(ValueError,'hash mismatch'):
            verify_deb.verify(self.fixture(self.replace(verify_deb.HELPER,body=bytes(changed))))
        changed=bytearray(signed_binary());changed[4]=0
        with self.assertRaisesRegex(ValueError,'ARMv7'):
            verify_deb.verify(self.fixture(self.replace(verify_deb.HELPER,body=bytes(changed))))

    def test_build_version_matches_app_and_request(self):
        with self.assertRaisesRegex(ValueError,'package build'):verify_deb.verify(self.fixture(),build=18)
        other=self.folder/'other';other.mkdir()
        with self.assertRaisesRegex(ValueError,'rebuild'):
            package_deb.stage_package(other,self.app,self.helper,self.plist,'0.4.0',18)

    @unittest.skipUnless(shutil.which('dpkg-deb'),'Native Linux package builder required')
    def test_actual_dpkg_builder_creates_verified_gzip_package(self):
        result=package_deb.build_package(self.app,self.helper,'0.4.0',17,self.folder/'native.deb',self.plist)
        self.assertEqual(result['version'],'0.4.0-17')


@unittest.skipUnless(shutil.which('sh'),'POSIX shell required for harmless maintainer script simulations')
class MaintainerScriptTests(DebFixture):
    def setUp(self):
        super().setUp();self.bin=self.folder/'bin';self.bin.mkdir();self.trace=self.folder/'trace'
        self.environment=dict(os.environ,PATH=str(self.bin),TRACE=str(self.trace),LOADED='1',CACHE_STYLE='modern')
        for command in ('launchctl','uicache','chown','chmod','mkdir','killall'):
            body='#!/bin/sh\nprintf "%s %s\\n" "'+command+'" "$*" >> "$TRACE"\n'
            if command=='launchctl':body+='if [ "${1:-}" = list ]; then [ "$LOADED" = 1 ]; else exit 0; fi\n'
            if command=='uicache':body+='if [ "${1:-}" = --help ] && [ "$CACHE_STYLE" = modern ]; then printf "%s\\n" "--path --unregister"; fi\nexit 0\n'
            path=self.bin/command;path.write_text(body,encoding='utf-8',newline='\n');path.chmod(0o755)

    def run_script(self,name,argument,content=None):
        path=self.folder/'script';path.write_text(content or package_deb.SCRIPTS[name],encoding='utf-8',newline='\n')
        return subprocess.run([shutil.which('sh'),str(path),argument],env=self.environment,capture_output=True,text=True)

    def test_scripts_are_valid_posix_shell(self):
        for name,content in package_deb.SCRIPTS.items():
            path=self.folder/name;path.write_text(content,encoding='utf-8',newline='\n')
            result=subprocess.run([shutil.which('sh'),'-n',str(path)],capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)

    def test_old_postrm_upgrade_does_not_touch_new_service_or_app(self):
        result=self.run_script('postrm','upgrade')
        self.assertEqual(result.returncode,0,result.stderr);self.assertFalse(self.trace.exists())

    def test_prerm_upgrade_unloads_only_own_service(self):
        result=self.run_script('prerm','upgrade');self.assertEqual(result.returncode,0,result.stderr)
        calls=self.trace.read_text(encoding='utf-8');self.assertIn('launchctl unload '+package_deb.DAEMON,calls)
        self.assertNotIn('SpringBoard',calls)

    def test_postinst_creates_private_mobile_state_and_is_repeatable(self):
        self.environment['LOADED']='0'
        first=self.run_script('postinst','configure');self.assertEqual(first.returncode,0,first.stderr)
        self.environment['LOADED']='1'
        second=self.run_script('postinst','configure');self.assertEqual(second.returncode,0,second.stderr)
        calls=self.trace.read_text(encoding='utf-8')
        self.assertEqual(calls.count('launchctl load '+package_deb.DAEMON),1)
        self.assertIn('chown mobile:mobile '+package_deb.SHARED,calls)
        self.assertIn('chmod 700 '+package_deb.SHARED,calls)
        self.assertNotIn('rm ',calls)

    def test_remove_uses_compatible_uicache_and_keeps_pairings(self):
        for style in ('modern','legacy'):
            self.environment['CACHE_STYLE']=style;self.trace.unlink(missing_ok=True)
            result=self.run_script('postrm','remove');self.assertEqual(result.returncode,0,result.stderr)
            calls=self.trace.read_text(encoding='utf-8');self.assertIn('uicache --help',calls)
            self.assertEqual('uicache -u '+package_deb.APP in calls,style=='modern')
            self.assertNotIn('rm ',calls);self.assertNotIn('launchctl',calls)

    def test_preinst_blocks_ipa_without_removing_it(self):
        containers=self.folder/'containers';existing=containers/'uuid/ShockStream.app';existing.mkdir(parents=True)
        payload=existing/'keep';payload.write_text('untouched',encoding='utf-8')
        script=package_deb.PREINST.replace('/var/containers/Bundle/Application',containers.as_posix())
        result=self.run_script('preinst','install',script)
        self.assertNotEqual(result.returncode,0);self.assertIn('IPA',result.stderr)
        self.assertEqual(payload.read_text(encoding='utf-8'),'untouched')


if __name__=='__main__':unittest.main()
