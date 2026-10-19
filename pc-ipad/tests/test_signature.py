import contextlib
import hashlib
import importlib.util
import io
from pathlib import Path
import plistlib
import struct
import tempfile
import unittest
import zipfile

spec=importlib.util.spec_from_file_location('verify_ipa',Path(__file__).resolve().parents[1]/'scripts/verify_ipa.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)

def signed_binary():
    libraries=[]
    for name in ('VideoToolbox','AudioToolbox'):
        path=f'/System/Library/Frameworks/{name}.framework/{name}'.encode()+b'\0'
        size=(24+len(path)+3)&~3
        libraries.append(struct.pack('<6I',0xc,size,24,0,0,0)+path+b'\0'*(size-24-len(path)))
    identifier=b'com.shock.test\0';hash_offset=44+len(identifier);directory_size=hash_offset+32
    blob_size=20+directory_size
    commands=b''.join(libraries)+struct.pack('<4I',0x25,16,0x90000,0x90200)+struct.pack('<4I',0x1d,16,4096,blob_size)
    header=struct.pack('<7I',0xfeedface,12,9,2,4,len(commands),0x200000)
    code=(header+commands).ljust(4096,b'\0')
    directory=struct.pack('>9I4BI',0xfade0c02,directory_size,0x20200,0,hash_offset,44,0,1,4096,32,2,0,12,0)+identifier+hashlib.sha256(code).digest()
    blob=struct.pack('>5I',0xfade0cc0,blob_size,1,0,20)+directory
    return code+blob

class SignatureTests(unittest.TestCase):
    def build_ipa(self,path,binary):
        info={'CFBundleIdentifier':'com.shock.stream.ipad','CFBundleExecutable':'ShockStream','MinimumOSVersion':'9.0','CFBundleShortVersionString':'0.1.0','CFBundleVersion':'2'}
        with zipfile.ZipFile(path,'w') as archive:
            archive.writestr('Payload/ShockStream.app/Info.plist',plistlib.dumps(info))
            archive.writestr('Payload/ShockStream.app/ShockStream',binary)

    def test_ldid_signature_with_zero_flags(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'client.ipa';self.build_ipa(path,signed_binary())
            with contextlib.redirect_stdout(io.StringIO()):result=module.verify(path)
            self.assertEqual(result['signatureFlags'],0)
            self.assertEqual(result['architecture'],'armv7')

    def test_signature_page_tampering_is_rejected(self):
        binary=bytearray(signed_binary());binary[2000]^=1
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'client.ipa';self.build_ipa(path,binary)
            with self.assertRaisesRegex(AssertionError,'hash mismatch'):module.verify(path)

if __name__=='__main__':unittest.main()
