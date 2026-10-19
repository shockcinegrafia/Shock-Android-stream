"""Windows user-session tray and explicitly selected login startup."""
from pathlib import Path
import subprocess
import sys
import threading

RUN_KEY = r'Software\Microsoft\Windows\CurrentVersion\Run'
RUN_NAME = 'ShockStream'


class InstanceGuard:
    """One host per interactive Windows session, including background startup."""
    def __init__(self):
        import ctypes as C
        self.kernel=C.WinDLL('kernel32',use_last_error=True)
        self.kernel.CreateMutexW.argtypes=[C.c_void_p,C.c_int32,C.c_wchar_p]
        self.kernel.CreateMutexW.restype=C.c_void_p
        self.kernel.CloseHandle.argtypes=[C.c_void_p]
        C.set_last_error(0)
        self.handle=self.kernel.CreateMutexW(None,False,r'Local\ShockStream.PC.Host')
        error=C.get_last_error()
        if not self.handle:raise OSError(error,'Não foi possível reservar a instância do Shock Stream')
        self.owner=error!=183

    def show_existing(self):
        import ctypes as C
        user=C.WinDLL('user32',use_last_error=True)
        user.FindWindowW.argtypes=[C.c_wchar_p,C.c_wchar_p];user.FindWindowW.restype=C.c_void_p
        user.ShowWindow.argtypes=[C.c_void_p,C.c_int32]
        user.SetForegroundWindow.argtypes=[C.c_void_p]
        handle=user.FindWindowW(None,'Shock Stream · Wi-Fi e monitor USB')
        if handle:user.ShowWindow(handle,9);user.SetForegroundWindow(handle)

    def close(self):
        if self.handle:self.kernel.CloseHandle(self.handle);self.handle=None


def startup_command():
    args = [sys.executable]
    if not getattr(sys, 'frozen', False):
        args.append(str(Path(__file__).with_name('host.py').resolve()))
    args.append('--background')
    result = subprocess.list2cmdline(args)
    if len(result) > 260:
        raise ValueError('Coloque o programa em uma pasta com caminho mais curto para iniciar com o Windows.')
    return result


def startup_enabled():
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            command, _ = winreg.QueryValueEx(key, RUN_NAME)
        return command == startup_command()
    except (OSError, ValueError):
        return False


def set_startup(enabled):
    import winreg
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
        if enabled:
            winreg.SetValueEx(key, RUN_NAME, 0, winreg.REG_SZ, startup_command())
        else:
            try:winreg.DeleteValue(key, RUN_NAME)
            except FileNotFoundError:pass


def icon_image():
    from PIL import Image, ImageDraw
    image = Image.new('RGBA', (64, 64), '#101721')
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((3,3,60,60),radius=13,outline='#4ce2bc',width=3)
    draw.line([(44,17),(20,17),(20,31),(43,31),(43,46),(19,46)],fill='#4ce2bc',width=6)
    return image


class Tray:
    def __init__(self, enqueue, show, resume, stop, quit_app):
        import pystray
        self.ready = threading.Event()
        def callback(action):
            return lambda icon,item:enqueue(action)
        self.icon = pystray.Icon('ShockStream', icon_image(), 'Shock Stream', pystray.Menu(
            pystray.MenuItem('Abrir Shock Stream', callback(show), default=True),
            pystray.MenuItem('Retomar iPad pelo USB', callback(resume)),
            pystray.MenuItem('Parar transmissão', callback(stop)),
            pystray.MenuItem('Sair completamente', callback(quit_app))))
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()

    def run(self):
        def setup(icon):
            icon.visible = True
            self.ready.set()
        self.icon.run(setup=setup)

    def stop(self):
        self.icon.stop()
        if threading.current_thread() is not self.thread:
            self.thread.join(timeout=1)
