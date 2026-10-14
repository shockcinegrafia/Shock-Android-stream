"""Monitor inventory and resolution changes restricted to the virtual display."""
import ctypes as C
import math
from touchscreen import RECT,DWORD,LONG

WORD=C.c_uint16
DM_POSITION=0x20
DM_DISPLAYORIENTATION=0x80
DM_BITSPERPEL=0x40000
DM_PELSWIDTH=0x80000
DM_PELSHEIGHT=0x100000
DM_DISPLAYFREQUENCY=0x400000
CDS_TEST=0x2
ENUM_CURRENT_SETTINGS=0xffffffff

class POINTL(C.Structure):
    _fields_=[('x',LONG),('y',LONG)]
class DISPLAY_FIELDS(C.Structure):
    _fields_=[('dmPosition',POINTL),('dmDisplayOrientation',DWORD),('dmDisplayFixedOutput',DWORD)]
class DEVICE_FIELDS(C.Union):
    _anonymous_=('display',)
    _fields_=[('printer',C.c_int16*8),('display',DISPLAY_FIELDS)]
class DISPLAY_FLAGS(C.Union):
    _fields_=[('dmDisplayFlags',DWORD),('dmNup',DWORD)]
class DEVMODEW(C.Structure):
    _anonymous_=('device','flags')
    _fields_=[('dmDeviceName',C.c_wchar*32),('dmSpecVersion',WORD),('dmDriverVersion',WORD),
              ('dmSize',WORD),('dmDriverExtra',WORD),('dmFields',DWORD),('device',DEVICE_FIELDS),
              ('dmColor',C.c_int16),('dmDuplex',C.c_int16),('dmYResolution',C.c_int16),
              ('dmTTOption',C.c_int16),('dmCollate',C.c_int16),('dmFormName',C.c_wchar*32),
              ('dmLogPixels',WORD),('dmBitsPerPel',DWORD),('dmPelsWidth',DWORD),
              ('dmPelsHeight',DWORD),('flags',DISPLAY_FLAGS),('dmDisplayFrequency',DWORD),
              ('dmICMMethod',DWORD),('dmICMIntent',DWORD),('dmMediaType',DWORD),
              ('dmDitherType',DWORD),('dmReserved1',DWORD),('dmReserved2',DWORD),
              ('dmPanningWidth',DWORD),('dmPanningHeight',DWORD)]

def fit_target(sourcew,sourceh,targetw,targeth,longest=1024):
    """Fit both display axes without stretching or enlarging the captured image.

    H.264 4:2:0 dimensions must be even. Truncating each axis by at most one pixel
    keeps the result within the source, the iPad display, and the quality limit.
    """
    values=(sourcew,sourceh,targetw,targeth,longest)
    if any(isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) or v<2 for v in values):
        raise ValueError('As dimensões da imagem e da tela devem ser pelo menos 2 pixels.')
    scale=min(1.0,targetw/sourcew,targeth/sourceh,longest/max(sourcew,sourceh))
    width=int(sourcew*scale)//2*2;height=int(sourceh*scale)//2*2
    if width<2 or height<2:raise ValueError('A proporção da imagem é incompatível com o vídeo.')
    return width,height

def _settings_api(api):
    if api is not None:return api
    user=C.windll.user32
    user.EnumDisplaySettingsW.argtypes=[C.c_wchar_p,DWORD,C.POINTER(DEVMODEW)]
    user.EnumDisplaySettingsW.restype=C.c_int
    user.ChangeDisplaySettingsExW.argtypes=[C.c_wchar_p,C.POINTER(DEVMODEW),C.c_void_p,DWORD,C.c_void_p]
    user.ChangeDisplaySettingsExW.restype=LONG
    return user

def _read_mode(api,device,index):
    mode=DEVMODEW();mode.dmSize=C.sizeof(mode)
    if not api.EnumDisplaySettingsW(device,index,C.byref(mode)):return None
    return mode

def set_ipad_resolution(monitor,width,height,*,api=None,monitor_provider=None):
    """Change only an identified virtual display to an iPad mini 1 mode.

    The display driver must advertise the requested resolution. The change is
    tested before applying and is not written to the Windows display registry.
    The monitor's device name, rather than its changing coordinates, identifies
    it after the change. Injectable dependencies permit tests without live I/O.
    """
    if not isinstance(monitor,dict) or monitor.get('virtual') is not True:
        raise ValueError('A resolução automática só pode alterar o monitor virtual.')
    if (isinstance(width,bool) or isinstance(height,bool) or
        not isinstance(width,int) or not isinstance(height,int) or
        (width,height) not in ((1024,768),(768,1024))):
        raise ValueError('O iPad mini 1 usa 1024 × 768 ou 768 × 1024 pixels.')
    device=monitor.get('device')
    if not isinstance(device,str) or not device:raise ValueError('Monitor virtual sem identificação do Windows.')
    user=_settings_api(api);current=_read_mode(user,device,ENUM_CURRENT_SETTINGS)
    if current is None:raise RuntimeError('Não foi possível consultar a resolução do monitor virtual.')
    if (current.dmPelsWidth,current.dmPelsHeight)!=(width,height):
        candidates=[];index=0
        while True:
            candidate=_read_mode(user,device,index)
            if candidate is None:break
            if (candidate.dmPelsWidth,candidate.dmPelsHeight)==(width,height):candidates.append(candidate)
            index+=1
        if not candidates:raise RuntimeError('O driver do monitor virtual não oferece a resolução '+str(width)+' × '+str(height)+'.')
        selected=next((m for m in candidates if m.dmDisplayFrequency==60),candidates[0])
        mode=DEVMODEW.from_buffer_copy(current)
        mode.dmPelsWidth=width;mode.dmPelsHeight=height
        mode.dmBitsPerPel=selected.dmBitsPerPel;mode.dmDisplayFrequency=selected.dmDisplayFrequency
        mode.dmDisplayOrientation=selected.dmDisplayOrientation
        mode.dmFields=DM_PELSWIDTH|DM_PELSHEIGHT|DM_BITSPERPEL|DM_DISPLAYFREQUENCY|DM_DISPLAYORIENTATION
        for flags in (CDS_TEST,0):
            result=user.ChangeDisplaySettingsExW(device,C.byref(mode),None,flags,None)
            if result:
                action='testar' if flags==CDS_TEST else 'aplicar'
                raise RuntimeError('Não foi possível '+action+' a resolução do monitor virtual: código '+str(result))
    provider=monitor_provider or monitors
    for updated in provider():
        if updated.get('device')==device:
            if (updated['width'],updated['height'])!=(width,height):
                raise RuntimeError('O Windows ainda não confirmou a nova resolução do monitor virtual.')
            return updated
    raise RuntimeError('O monitor virtual não está mais disponível na área de trabalho.')

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
