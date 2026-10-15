"""Monitor inventory and resolution changes restricted to the virtual display."""
import ctypes as C
import math
import time
from touchscreen import RECT,DWORD,LONG

WORD=C.c_uint16
DM_POSITION=0x20
DM_DISPLAYORIENTATION=0x80
DM_BITSPERPEL=0x40000
DM_PELSWIDTH=0x80000
DM_PELSHEIGHT=0x100000
DM_DISPLAYFREQUENCY=0x400000
CDS_TEST=0x2
CDS_UPDATEREGISTRY=0x1
CDS_NORESET=0x10000000
ENUM_CURRENT_SETTINGS=0xffffffff
ENUM_REGISTRY_SETTINGS=0xfffffffe

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

def _inventory_api(api=None):
    if api is not None:return api
    user=C.windll.user32
    user.EnumDisplayDevicesW.argtypes=[C.c_wchar_p,DWORD,C.POINTER(DISPLAY_DEVICE),DWORD]
    user.EnumDisplayDevicesW.restype=C.c_int
    user.GetMonitorInfoW.argtypes=[C.c_void_p,C.POINTER(MONITORINFOEX)]
    user.GetMonitorInfoW.restype=C.c_int
    return user

def is_virtual_display(*values):
    """Driver labels and PnP identifiers vary between versions of MttVDD."""
    text=' '.join(''.join(ch for ch in str(value).lower() if ch.isalnum()) for value in values)
    return any(word in text for word in ('virtualdisplay','iddsample','mttvdd'))

def _display_device(api,parent,index,flags=0):
    device=DISPLAY_DEVICE();device.cb=C.sizeof(device)
    if not api.EnumDisplayDevicesW(parent,index,C.byref(device),flags):return None
    return device

def display_adapters(api=None):
    """Include inactive adapters and their monitor hardware/interface IDs."""
    user=_inventory_api(api);result=[];index=0
    while True:
        device=_display_device(user,None,index)
        if device is None:break
        children=[];child_index=0
        while True:
            child=_display_device(user,device.DeviceName,child_index)
            if child is None:break
            interface=_display_device(user,device.DeviceName,child_index,1)
            children.append(dict(device=child.DeviceName,name=child.DeviceString,hardwareId=child.DeviceID,
                                 interfaceId=interface.DeviceID if interface else '',stateFlags=int(child.StateFlags)))
            child_index+=1
        hardware=[device.DeviceID]+[value for child in children for value in (child['hardwareId'],child['interfaceId'])]
        result.append(dict(device=device.DeviceName,adapter=device.DeviceString,hardwareIds=[value for value in hardware if value],
                           children=children,stateFlags=int(device.StateFlags),attached=bool(device.StateFlags&1),
                           primary=bool(device.StateFlags&4),virtual=is_virtual_display(device.DeviceString,*hardware,*[child['name'] for child in children])))
        index+=1
    return result

def monitors(api=None):
    user=_inventory_api(api);adapters={item['device']:item for item in display_adapters(user)}
    result=[]
    callback_type=getattr(C,'WINFUNCTYPE',C.CFUNCTYPE)(C.c_int,C.c_void_p,C.c_void_p,C.POINTER(RECT),C.c_ssize_t)
    def callback(handle,dc,rect,data):
        info=MONITORINFOEX();info.cbSize=C.sizeof(info)
        if user.GetMonitorInfoW(handle,C.byref(info)):
            r=info.rcMonitor;adapter=adapters.get(info.szDevice,dict(device=info.szDevice,adapter='Monitor',virtual=False))
            result.append(dict(adapter,left=r.left,top=r.top,width=r.right-r.left,height=r.bottom-r.top,
                               primary=bool(info.dwFlags&1),attached=True))
        return 1
    callback_object=callback_type(callback)
    user.EnumDisplayMonitors(None,None,callback_object,0)
    return sorted(result,key=lambda m:(not m['primary'],m['left'],m['top']))

class GUID(C.Structure):
    _fields_=[('Data1',DWORD),('Data2',WORD),('Data3',WORD),('Data4',C.c_ubyte*8)]
class SP_DEVINFO_DATA(C.Structure):
    _fields_=[('cbSize',DWORD),('ClassGuid',GUID),('DevInst',DWORD),('Reserved',C.c_size_t)]

def _pnp_api(api=None):
    if api is not None:return api
    api=C.WinDLL('setupapi',use_last_error=True)
    api.SetupDiGetClassDevsW.argtypes=[C.c_void_p,C.c_wchar_p,C.c_void_p,DWORD]
    api.SetupDiGetClassDevsW.restype=C.c_void_p
    api.SetupDiEnumDeviceInfo.argtypes=[C.c_void_p,DWORD,C.POINTER(SP_DEVINFO_DATA)]
    api.SetupDiEnumDeviceInfo.restype=C.c_int
    api.SetupDiGetDeviceRegistryPropertyW.argtypes=[C.c_void_p,C.POINTER(SP_DEVINFO_DATA),DWORD,C.POINTER(DWORD),C.POINTER(C.c_ubyte),DWORD,C.POINTER(DWORD)]
    api.SetupDiGetDeviceRegistryPropertyW.restype=C.c_int
    api.SetupDiDestroyDeviceInfoList.argtypes=[C.c_void_p]
    api.SetupDiDestroyDeviceInfoList.restype=C.c_int
    return api

def _device_property(api,handle,device,prop):
    needed=DWORD();kind=DWORD();size=4096
    for _ in range(2):
        buffer=(C.c_ubyte*size)()
        if api.SetupDiGetDeviceRegistryPropertyW(handle,C.byref(device),prop,C.byref(kind),buffer,size,C.byref(needed)):
            return bytes(buffer[:min(needed.value,size)]).decode('utf-16-le',errors='replace').strip('\x00')
        if needed.value<=size or needed.value>65536:return ''
        size=needed.value
    return ''

def virtual_driver_devices(api=None):
    """Read present PnP hardware IDs through SetupAPI, without CIM or elevation."""
    api=_pnp_api(api);handle=api.SetupDiGetClassDevsW(None,None,None,0x2|0x4)
    if handle in (None,0,C.c_void_p(-1).value):raise OSError('Não foi possível consultar os dispositivos de vídeo do Windows.')
    result=[];index=0
    try:
        while True:
            device=SP_DEVINFO_DATA();device.cbSize=C.sizeof(device)
            if not api.SetupDiEnumDeviceInfo(handle,index,C.byref(device)):
                error=getattr(api,'last_error',None)
                if error is None:error=getattr(C,'get_last_error',lambda:0)()
                if error not in (0,259):raise OSError(error,'A consulta de dispositivos do Windows foi interrompida.')
                break
            hardware=_device_property(api,handle,device,1).split('\x00')
            # FriendlyName is optional; DeviceDesc remains available on disabled devices.
            name=_device_property(api,handle,device,12) or _device_property(api,handle,device,0)
            if is_virtual_display(name,*hardware):result.append(dict(name=name,hardwareIds=[item for item in hardware if item],devInst=int(device.DevInst)))
            index+=1
    finally:api.SetupDiDestroyDeviceInfoList(handle)
    return result

def virtual_monitor_status(*,monitor_provider=None,adapter_provider=None,driver_provider=None):
    screens=(monitor_provider or monitors)();adapters=(adapter_provider or display_adapters)()
    active=[item for item in screens if item.get('virtual')]
    matching=[item for item in adapters if item.get('virtual')]
    result=dict(monitors=active,adapters=matching,devices=[])
    if active:return dict(result,state='active',message='Monitor virtual detectado e ativo como tela do Windows.')
    if matching:
        state='inactive' if any(not item.get('attached') for item in matching) else 'unavailable'
        return dict(result,state=state,message='O adaptador do monitor virtual está instalado, mas ainda não oferece uma tela ativa para captura.')
    try:result['devices']=(driver_provider or virtual_driver_devices)()
    except OSError as exc:return dict(result,state='unknown',message='Não foi possível confirmar o driver do monitor virtual: '+str(exc))
    if result['devices']:
        return dict(result,state='driver-only',message='O dispositivo Root\\MttVDD está instalado, mas o Windows não publicou seu adaptador de vídeo. Reinicie o PC ou repare o driver pelo aplicativo.')
    return dict(result,state='missing',message='O driver Root\\MttVDD não foi encontrado. Use Criar segundo monitor. As áreas de trabalho da Visão de Tarefas do Windows não criam um monitor adicional.')

def ensure_virtual_monitor(*,api=None,monitor_provider=None,adapter_provider=None,driver_provider=None,timeout=2.0):
    """Attach an installed inactive virtual output, preserving the primary screen."""
    provider=monitor_provider or monitors
    status=virtual_monitor_status(monitor_provider=provider,adapter_provider=adapter_provider,driver_provider=driver_provider)
    if status['state']=='active':return status['monitors'][0]
    if status['state']!='inactive':raise RuntimeError(status['message'])
    adapter=next(item for item in status['adapters'] if not item.get('attached'))
    device=adapter['device'];user=_settings_api(api);modes=[];index=0
    while True:
        mode=_read_mode(user,device,index)
        if mode is None:break
        if mode.dmPelsWidth>=2 and mode.dmPelsHeight>=2:modes.append(mode)
        index+=1
    if not modes:raise RuntimeError('O driver do monitor virtual está inativo e não anunciou resoluções. Reinicie o PC ou repare o driver.')
    selected=next((m for m in modes if (m.dmPelsWidth,m.dmPelsHeight,m.dmDisplayFrequency)==(1024,768,60)),None)
    if selected is None:selected=next((m for m in modes if (m.dmPelsWidth,m.dmPelsHeight)==(1024,768)),modes[0])
    mode=DEVMODEW.from_buffer_copy(selected);screens=provider()
    if not screens:raise RuntimeError('O Windows não apresentou uma tela principal para estender a área de trabalho.')
    edge=max(screens,key=lambda item:item['left']+item['width'])
    mode.dmPosition=POINTL(edge['left']+edge['width'],edge['top'])
    mode.dmFields=DM_POSITION|DM_PELSWIDTH|DM_PELSHEIGHT|DM_BITSPERPEL|DM_DISPLAYFREQUENCY|DM_DISPLAYORIENTATION
    previous=_read_mode(user,device,ENUM_REGISTRY_SETTINGS)
    for flags in (CDS_TEST,CDS_UPDATEREGISTRY|CDS_NORESET):
        result=user.ChangeDisplaySettingsExW(device,C.byref(mode),None,flags,None)
        if result:raise RuntimeError('Não foi possível ativar o monitor virtual: código '+str(result)+'. Reinicie o PC se o driver acabou de ser instalado.')
    result=user.ChangeDisplaySettingsExW(None,None,None,0,None)
    if result:
        if previous is not None:
            # Revert the staged registry setting if Windows cannot apply the attachment.
            user.ChangeDisplaySettingsExW(device,C.byref(previous),None,CDS_UPDATEREGISTRY|CDS_NORESET,None)
            user.ChangeDisplaySettingsExW(None,None,None,0,None)
        raise RuntimeError('O Windows não aplicou a extensão do monitor virtual: código '+str(result))
    deadline=time.monotonic()+max(0,timeout)
    while True:
        for monitor in provider():
            if monitor.get('device')==device and monitor.get('virtual'):return monitor
        if time.monotonic()>=deadline:break
        time.sleep(0.1)
    raise RuntimeError('O driver aceitou a ativação, mas o monitor virtual ainda não apareceu. Reinicie o PC ou repare o driver.')

def extend_desktop():
    result=C.windll.user32.SetDisplayConfig(0,None,0,None,0x80|0x4)
    if result:raise RuntimeError('Não foi possível estender a área de trabalho: código '+str(result))
