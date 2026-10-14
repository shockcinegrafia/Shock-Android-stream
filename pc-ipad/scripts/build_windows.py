"""Package without importing vgamepad (which would connect to a missing bus)."""
import importlib.util
from pathlib import Path
import PyInstaller.__main__

spec=importlib.util.find_spec('vgamepad')
assert spec and spec.submodule_search_locations
dll=Path(next(iter(spec.submodule_search_locations)))/'win/vigem/client/x64/ViGEmClient.dll'
assert dll.is_file()
PyInstaller.__main__.run([
    '--noconfirm','--clean','--onedir','--windowed','--name','ShockStream',
    '--collect-all','av','--collect-all','soundcard','--hidden-import','_cffi_backend',
    '--add-binary',str(dll)+';vgamepad/win/vigem/client/x64',
    '--distpath','dist','--workpath','build/pc','--specpath','build/pc',
    'pc-ipad/windows/host.py'
])
