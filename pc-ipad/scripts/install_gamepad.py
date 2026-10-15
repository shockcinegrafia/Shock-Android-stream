"""Install the pinned pure-Python gamepad package without executing setup.py.

Its normal setup scans the whole registry and can launch a driver installer.
We verify the published sdist hash, copy Python/DLL files, and keep the source archive.
"""
import csv
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import sysconfig
import tarfile
import urllib.request

VERSION='0.1.0'
EXPECTED_SHA256='57f6bd01aec0c172947517fb782d150ef9b285f7f4d524c317374fa5c24a89de'
with urllib.request.urlopen(f'https://pypi.org/pypi/vgamepad/{VERSION}/json',timeout=30) as response:
    release=json.load(response)
source=next(item for item in release['urls'] if item['packagetype']=='sdist')
with urllib.request.urlopen(source['url'],timeout=60) as response:blob=response.read()
digest=hashlib.sha256(blob).hexdigest()
assert digest==EXPECTED_SHA256==source['digests']['sha256'],'vgamepad source checksum mismatch'
purelib=Path(sysconfig.get_paths()['purelib']).resolve()
metadata=purelib/f'vgamepad-{VERSION}.dist-info';metadata.mkdir(parents=True,exist_ok=True)
records=[]
with tarfile.open(fileobj=io.BytesIO(blob),mode='r:gz') as archive:
    for entry in archive.getmembers():
        if not entry.isfile():continue
        parts=PurePosixPath(entry.name).parts
        if '..' in parts or len(parts)<2:raise ValueError('Invalid source path')
        relative=Path(*parts[1:])
        if parts[1]=='vgamepad' and relative.suffix.lower() in ('.py','.dll'):
            destination=(purelib/relative).resolve()
            assert destination.is_relative_to(purelib/'vgamepad')
        elif relative.name=='PKG-INFO' and len(parts)==2:destination=metadata/'METADATA'
        elif any(word in relative.name.lower() for word in ('license','copying')):
            destination=metadata/relative.name
        else:continue
        destination.parent.mkdir(parents=True,exist_ok=True)
        destination.write_bytes(archive.extractfile(entry).read())
        records.append((str(destination.relative_to(purelib)).replace('\\','/'),'',''))
assert (purelib/'vgamepad/win/vigem/client/x64/ViGEmClient.dll').is_file()
with (metadata/'RECORD').open('w',newline='') as file:csv.writer(file).writerows(records)
sources=Path('dist/third-party-sources');sources.mkdir(parents=True,exist_ok=True)
(sources/f'vgamepad-{VERSION}.tar.gz').write_bytes(blob)
(sources/'vgamepad-source.json').write_text(json.dumps({'version':VERSION,'url':source['url'],'sha256':digest},indent=2))
print('Installed gamepad Python/DLL files; no registry scan, driver install, or bus connection performed.')
