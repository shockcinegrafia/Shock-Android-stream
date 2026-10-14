"""Fetch official pinned redistributable driver packages; execute no installer."""
import hashlib
import json
from pathlib import Path
import struct
import urllib.request
import zipfile
import io
import xml.etree.ElementTree as ET

ROOT=Path('pc-ipad/drivers');ROOT.mkdir(parents=True,exist_ok=True)
PACKAGES=[
 ('ViGEmBus.exe','https://github.com/nefarius/ViGEmBus/releases/download/v1.22.0/ViGEmBus_1.22.0_x64_x86_arm64.exe','89220a7865076b342892f98865f3499fb7c4cfd673159e89d352c360fd014c6a'),
 ('vdd.zip','https://github.com/VirtualDrivers/Virtual-Display-Driver/releases/download/25.7.23/VirtualDisplayDriver-x86.Driver.Only.zip','e24210692b442b39af763536330ce78b423f19342b7a7792c26de3944e418b3a')]
manifest=[]
for name,url,digest in PACKAGES:
    with urllib.request.urlopen(url,timeout=90) as response:data=response.read()
    assert hashlib.sha256(data).hexdigest()==digest,'driver checksum mismatch'
    if name.endswith('.zip'):
        folder=ROOT/'vdd';folder.mkdir(exist_ok=True)
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            for file in ('MttVDD.inf','MttVDD.dll','mttvdd.cat','vdd_settings.xml'):
                (folder/file).write_bytes(archive.read('VirtualDisplayDriver/'+file))
        binary=(folder/'MttVDD.dll').read_bytes();pe=struct.unpack_from('<I',binary,0x3c)[0]
        assert struct.unpack_from('<H',binary,pe+4)[0]==0x8664,'x64 display driver required'
        config=ET.parse(folder/'vdd_settings.xml');root=config.getroot()
        resolution=root.find('resolutions');resolution.clear()
        for width,height in [(1024,768),(768,1024)]:
            item=ET.SubElement(resolution,'resolution')
            for key,value in [('width',width),('height',height),('refresh_rate',60)]:ET.SubElement(item,key).text=str(value)
        global_rates=root.find('global');global_rates.clear();ET.SubElement(global_rates,'g_refresh_rate').text='60'
        config.write(folder/'vdd_settings.xml',encoding='utf-8',xml_declaration=True)
    else:(ROOT/name).write_bytes(data)
    manifest.append({'name':name,'url':url,'sha256':digest})
for name,url in [('VirtualDisplay-LICENSE.txt','https://raw.githubusercontent.com/VirtualDrivers/Virtual-Display-Driver/25.7.23/LICENSE'),
                 ('ViGEmBus-LICENSE.txt','https://raw.githubusercontent.com/nefarius/ViGEmBus/v1.22.0/LICENSE')]:
    with urllib.request.urlopen(url,timeout=30) as response:(ROOT/name).write_bytes(response.read())
(ROOT/'manifest.json').write_text(json.dumps(manifest,indent=2))
print('Pinned driver files bundled; no driver installed.')
