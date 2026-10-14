"""Keep dependency license files and exact installed versions with the executable."""
import importlib.metadata
import json
from pathlib import Path
import shutil
import sys

target=Path(sys.argv[1]);target.mkdir(parents=True,exist_ok=True)
versions={}
for name in ('av','mss','numpy','soundcard','vgamepad','cffi','pyinstaller','zeroconf','ifaddr'):
    dist=importlib.metadata.distribution(name);versions[name]=dist.version
    for file in dist.files or []:
        if any(word in file.name.lower() for word in ('license','copying','notice')):
            origin=dist.locate_file(file)
            if origin.is_file():
                destination=target/name/str(file)
                destination.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(origin,destination)
import av
from av._core import library_meta, ffmpeg_version_info
(target/'versions.json').write_text(json.dumps({'python':sys.version,'dependencies':versions,'ffmpeg_version':ffmpeg_version_info,'ffmpeg_libraries':library_meta},indent=2))
