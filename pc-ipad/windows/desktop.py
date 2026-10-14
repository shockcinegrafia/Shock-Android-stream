"""Monitor inventory and user-requested desktop extension."""
import ctypes as C
from touchscreen import RECT,DWORD,LONG

class DISPLAY_DEVICE(C.Structure):
    _fields_=[('cb',DWORD),('DeviceName',C.c_wchar*32),('DeviceString',C.c_wchar*128),
              ('StateFlags',DWORD),('DeviceID',C.c_wchar*128),('DeviceKey',C.c_wchar*128)]
class MONITORINFOEX(C.Structure):
    _fields_=[('cbSize',DWORD),('rcMonitor',RECT),('rcWork',RECT),('dwFlags',DWORD),('szDevice',C.c_wchar*32)]

def dpi_aware():
    try:C.windll.user32.SetProcessDpiAwarenessContext(C.c_void_p(-4))
    except (AttributeError,OSError):pass

def monitors():
    user=C.windll.user32;adapters={};index=0
    user.EnumDisplayDevicesW.argtypes=[C.c_wchar_p,DWORD,C.POINTER(DISPLAY_DEVICE),DWORD]
    user.GetMonitorInfoW.argtypes=[C.c_void_p,C.POINTER(MONITORINFOEX)]
    while True:
        device=DISPLAY_DEVICE();device.cb=C.sizeof(device)
        if not user.EnumDisplayDevicesW(None,index,C.byref(device),0):break
        adapters[device.DeviceName]=device.DeviceString;index+=1
    result=[]
    callback_type=C.WINFUNCTYPE(C.c_int,C.c_void_p,C.c_void_p,C.POINTER(RECT),C.c_ssize_t)
    def callback(handle,dc,rect,data):
        info=MONITORINFOEX();info.cbSize=C.sizeof(info)
        if user.GetMonitorInfoW(handle,C.byref(info)):
            r=info.rcMonitor;adapter=adapters.get(info.szDevice,'Monitor')
            virtual=any(word in adapter.lower() for word in ('virtual display','iddsample','mttvdd'))
            result.append(dict(left=r.left,top=r.top,width=r.right-r.left,height=r.bottom-r.top,
                               device=info.szDevice,adapter=adapter,virtual=virtual,primary=bool(info.dwFlags&1)))
        return 1
    callback_object=callback_type(callback)
    user.EnumDisplayMonitors(None,None,callback_object,0)
    return sorted(result,key=lambda m:(not m['primary'],m['left'],m['top']))

def extend_desktop():
    result=C.windll.user32.SetDisplayConfig(0,None,0,None,0x80|0x4)
    if result:raise RuntimeError('Não foi possível estender a área de trabalho: código '+str(result))
