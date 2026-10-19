"""Build and verify a rootful iOS 9 DEB on Linux without touching a device."""
import argparse
import json
from pathlib import Path
import plistlib
import re
import shutil
import subprocess
import tempfile

PACKAGE='com.shock.stream.ipad'
APP='/Applications/ShockStream.app'
HELPER='/usr/libexec/shockstream-waked'
DAEMON='/Library/LaunchDaemons/com.shock.stream.wake.plist'
SHARED='/var/mobile/Library/Application Support/ShockStream'

PREINST='''#!/bin/sh
set -eu
case "${1:-}" in
 install|upgrade)
  if [ -L /Applications/ShockStream.app ]; then
   echo "ShockStream: caminho inesperado do aplicativo; link simbólico recusado." >&2
   exit 1
  fi
  for candidate in /var/containers/Bundle/Application/*/ShockStream.app /var/mobile/Containers/Bundle/Application/*/ShockStream.app /var/mobile/Applications/*/ShockStream.app; do
   if [ -d "$candidate" ]; then
    echo "ShockStream: existe uma instalação IPA. Preserve o pareamento e remova o IPA pelo Filza ou pela tela inicial antes de instalar este DEB. Nenhum aplicativo ou dado foi apagado." >&2
    exit 1
   fi
  done
  ;;
esac
exit 0
'''

PRERM='''#!/bin/sh
set -eu
case "${1:-}" in
 remove|upgrade|deconfigure)
  if command -v launchctl >/dev/null 2>&1 && launchctl list com.shock.stream.wake >/dev/null 2>&1; then
   launchctl unload /Library/LaunchDaemons/com.shock.stream.wake.plist
  fi
  if command -v killall >/dev/null 2>&1; then killall -TERM ShockStream >/dev/null 2>&1 || true; fi
  ;;
esac
exit 0
'''

# Old UIKit Tools ignores arguments: the help probe itself rebuilds the cache.
# Modern tools advertise targeted registration. Do not require modern flags.
CACHE_FUNCTION='''refresh_icon() {
 action="$1"
 if ! command -v uicache >/dev/null 2>&1; then
  echo "ShockStream: uicache não está disponível para atualizar o ícone." >&2
  return 1
 fi
 if cache_help="$(uicache --help 2>&1)"; then
  case "$cache_help" in
   *--path*|*"-p path"*)
    if [ "$action" = remove ]; then
     case "$cache_help" in
      *--unregister*|*"-u path"*) uicache -u /Applications/ShockStream.app ;;
      *) uicache ;;
     esac
    else uicache -p /Applications/ShockStream.app; fi
    ;;
   *) if [ -n "$cache_help" ]; then uicache; fi ;;
  esac
 else uicache; fi
}
'''

POSTINST='''#!/bin/sh
set -eu
'''+CACHE_FUNCTION+'''case "${1:-}" in
 configure|abort-upgrade|abort-remove|abort-deconfigure)
  app=/Applications/ShockStream.app
  shared='/var/mobile/Library/Application Support/ShockStream'
  if [ -L "$app" ] || [ -L "$shared" ]; then
   echo "ShockStream: caminho inesperado na instalação; links simbólicos recusados." >&2
   exit 1
  fi
  chown -R root:wheel "$app"
  chmod 755 "$app" "$app/ShockStream" /usr/libexec/shockstream-waked
  chown root:wheel /usr/libexec/shockstream-waked /Library/LaunchDaemons/com.shock.stream.wake.plist
  chmod 644 /Library/LaunchDaemons/com.shock.stream.wake.plist
  mkdir -p "$shared"
  chown mobile:mobile "$shared"
  chmod 700 "$shared"
  refresh_icon install
  if ! launchctl list com.shock.stream.wake >/dev/null 2>&1; then
   launchctl load /Library/LaunchDaemons/com.shock.stream.wake.plist
  fi
  ;;
esac
exit 0
'''

POSTRM='''#!/bin/sh
set -eu
'''+CACHE_FUNCTION+'''case "${1:-}" in
 remove|purge)
  # Files are already gone. Preserve pairings for a reinstall.
  if command -v uicache >/dev/null 2>&1; then refresh_icon remove; fi
  ;;
 upgrade|failed-upgrade|abort-upgrade|abort-install|disappear)
  # Old postrm runs after new files are unpacked: leave the new service alone.
  ;;
esac
exit 0
'''
SCRIPTS={'preinst':PREINST,'prerm':PRERM,'postinst':POSTINST,'postrm':POSTRM}


def checked_version(version,build):
    if not isinstance(version,str) or not re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+',version):
        raise ValueError('Version must contain three numeric components.')
    if isinstance(build,bool) or not isinstance(build,int) or build<1:raise ValueError('Build must be a positive integer.')
    return f'{version}-{build}'


def stage_package(root,app,helper,launchdaemon,version,build):
    """Stage fixed paths only. Installation scripts are never executed here."""
    package_version=checked_version(version,build)
    root=Path(root);app=Path(app);helper=Path(helper);launchdaemon=Path(launchdaemon)
    if not app.is_dir() or app.is_symlink():raise ValueError('Application directory missing or symlinked.')
    if any(path.is_symlink() for path in app.rglob('*')):raise ValueError('Application symlinks are not supported.')
    if not helper.is_file() or helper.is_symlink():raise ValueError('Wake helper missing or symlinked.')
    info=plistlib.loads((app/'Info.plist').read_bytes())
    if (info.get('CFBundleIdentifier')!=PACKAGE or info.get('CFBundleExecutable')!='ShockStream' or
        info.get('CFBundleShortVersionString')!=version or str(info.get('CFBundleVersion'))!=str(build)):
        raise ValueError('App identity/version/build differs from the package request; rebuild the app first.')
    destination=root/APP.lstrip('/');destination.parent.mkdir(parents=True,exist_ok=True)
    shutil.copytree(app,destination)
    marker=dict(package=PACKAGE,version=version,build=str(build),architecture='iphoneos-arm')
    (destination/'.shock-deb').write_text(json.dumps(marker,sort_keys=True)+'\n',encoding='utf-8')
    for source,target in ((helper,HELPER),(launchdaemon,DAEMON)):
        path=root/target.lstrip('/');path.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source,path)
    control=root/'DEBIAN';control.mkdir()
    (control/'control').write_text(
        f'Package: {PACKAGE}\nName: ShockStream\nVersion: {package_version}\nArchitecture: iphoneos-arm\n'
        'Maintainer: ShockStream\nSection: Utilities\nPriority: optional\n'
        'Depends: firmware (>= 9.0), firmware (<< 10.0), uikittools\n'
        'Description: PC streaming and USB wake helper for iPad mini 1 on iOS 9.\n',encoding='utf-8')
    for name,content in SCRIPTS.items():(control/name).write_text(content,encoding='utf-8',newline='\n')
    for path in [root]+list(root.rglob('*')):path.chmod(0o755 if path.is_dir() else 0o644)
    for path in (destination/'ShockStream',root/HELPER.lstrip('/')):path.chmod(0o755)
    for name in SCRIPTS:(control/name).chmod(0o755)
    return marker


def build_package(app,helper,version,build,out,launchdaemon=None):
    from verify_deb import verify
    out=Path(out).resolve();out.parent.mkdir(parents=True,exist_ok=True)
    launchdaemon=Path(launchdaemon) if launchdaemon else Path(__file__).resolve().parents[1]/'wake/launchdaemon.plist'
    with tempfile.TemporaryDirectory(prefix='shockstream-deb-') as folder:
        root=Path(folder)/'root';root.mkdir();stage_package(root,app,helper,launchdaemon,version,build)
        command=['dpkg-deb','--root-owner-group','--uniform-compression','-Zgzip','-z9','--build',str(root),str(out)]
        try:subprocess.run(command,check=True,capture_output=True,text=True)
        except FileNotFoundError as exc:raise RuntimeError('Build on Linux with dpkg-deb installed.') from exc
        except subprocess.CalledProcessError as exc:raise RuntimeError('dpkg-deb failed: '+exc.stderr.strip()) from exc
    return verify(out,version=version,build=build)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--app',required=True,type=Path);parser.add_argument('--helper',required=True,type=Path)
    parser.add_argument('--version',default='0.4.0');parser.add_argument('--build',required=True,type=int)
    parser.add_argument('--out',default=Path('dist/ShockStream-iOS9-ARMv7.deb'),type=Path)
    parser.add_argument('--launchdaemon',type=Path)
    parser.add_argument('--verify',action='store_true',help='Every package is verified; accepted for explicit CI invocation.')
    args=parser.parse_args()
    print(json.dumps(build_package(args.app,args.helper,args.version,args.build,args.out,args.launchdaemon),indent=2))


if __name__=='__main__':main()
