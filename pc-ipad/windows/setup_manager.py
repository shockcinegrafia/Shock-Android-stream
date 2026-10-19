"""Bundled driver launchers; invoked by explicit UI actions, never on startup."""
import ctypes as C
from pathlib import Path
import subprocess
import sys
import time

def resource_root():return Path(getattr(sys,'_MEIPASS',Path(__file__).resolve().parents[1]))

class SHELLEXECUTEINFO(C.Structure):
    _fields_=[('cbSize',C.c_uint32),('fMask',C.c_uint32),('hwnd',C.c_void_p),('lpVerb',C.c_wchar_p),
              ('lpFile',C.c_wchar_p),('lpParameters',C.c_wchar_p),('lpDirectory',C.c_wchar_p),
              ('nShow',C.c_int),('hInstApp',C.c_void_p),('lpIDList',C.c_void_p),
              ('lpClass',C.c_wchar_p),('hkeyClass',C.c_void_p),('dwHotKey',C.c_uint32),
              ('hIcon',C.c_void_p),('hProcess',C.c_void_p)]

def elevated(executable,args=(),visible=False):
    info=SHELLEXECUTEINFO();info.cbSize=C.sizeof(info);info.fMask=0x40|0x100
    info.lpVerb='runas';info.lpFile=str(executable);info.lpParameters=subprocess.list2cmdline(list(map(str,args)))
    info.lpDirectory=str(Path(executable).parent);info.nShow=1 if visible else 0
    shell=C.WinDLL('shell32',use_last_error=True);shell.ShellExecuteExW.argtypes=[C.POINTER(SHELLEXECUTEINFO)]
    if not shell.ShellExecuteExW(C.byref(info)):raise RuntimeError('Instalação cancelada ou não autorizada pelo Windows')
    kernel=C.WinDLL('kernel32',use_last_error=True)
    kernel.WaitForSingleObject.argtypes=[C.c_void_p,C.c_uint32];kernel.GetExitCodeProcess.argtypes=[C.c_void_p,C.POINTER(C.c_uint32)];kernel.CloseHandle.argtypes=[C.c_void_p]
    try:
        kernel.WaitForSingleObject(info.hProcess,0xffffffff)
        code=C.c_uint32();kernel.GetExitCodeProcess(info.hProcess,C.byref(code))
    finally:kernel.CloseHandle(info.hProcess)
    if code.value not in (0,3010,1641):raise RuntimeError('O instalador retornou o código '+str(code.value))
    return code.value

def install_gamepad():
    return elevated(resource_root()/'drivers'/'ViGEmBus.exe',visible=True)

def monitor_driver(uninstall=False):
    root=resource_root()
    return elevated(root/'DriverSetup.exe',('--uninstall' if uninstall else '--install',root/'drivers'/'vdd'/'MttVDD.inf'))

def prepare_apple_usb():
    # Apple binaries remain in Apple's installer, fetched/verified by Windows Package Manager.
    from usbmux import diagnostics
    status=diagnostics()
    if status['status'] in ('ready','no_device'):
        return status['message']
    if status['status']=='protocol_error':
        raise RuntimeError(status['message'])
    command=['winget','install','--id','Apple.iTunes','--exact','--source','winget',
             '--interactive','--accept-source-agreements','--disable-interactivity']
    result=subprocess.run(command,capture_output=True,creationflags=subprocess.CREATE_NO_WINDOW)
    if result.returncode:raise RuntimeError('O suporte Apple não foi instalado. Confira o Windows Package Manager e a instalação do iTunes. Código '+str(result.returncode))
    for _ in range(10):
        status=diagnostics()
        if status['status'] in ('ready','no_device'):
            return status['message']
        time.sleep(0.5)
    raise RuntimeError('Instalação concluída, mas o serviço USB Apple não respondeu. Reinicie o Apple Mobile Device Service ou o Windows e tente novamente. '+status['message'])
