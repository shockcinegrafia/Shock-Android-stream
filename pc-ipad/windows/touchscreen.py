"""Native Windows multitouch injection, mapped to the selected monitor."""
import ctypes as C
import math
import logging
import threading
import time

DWORD=C.c_uint32;LONG=C.c_int32
DOWN=0x10000;UPDATE=0x20000;UP=0x40000;CANCELED=0x8000;CONTACT=4;INRANGE=2

class POINT(C.Structure):_fields_=[('x',LONG),('y',LONG)]
class RECT(C.Structure):_fields_=[('left',LONG),('top',LONG),('right',LONG),('bottom',LONG)]
class POINTER_INFO(C.Structure):
    _fields_=[('pointerType',DWORD),('pointerId',DWORD),('frameId',DWORD),('pointerFlags',DWORD),
              ('sourceDevice',C.c_void_p),('hwndTarget',C.c_void_p),('ptPixelLocation',POINT),
              ('ptHimetricLocation',POINT),('ptPixelLocationRaw',POINT),('ptHimetricLocationRaw',POINT),
              ('dwTime',DWORD),('historyCount',DWORD),('InputData',LONG),('keyStates',DWORD),
              ('PerformanceCount',C.c_uint64),('ButtonChangeType',LONG)]
class POINTER_TOUCH_INFO(C.Structure):
    _fields_=[('pointerInfo',POINTER_INFO),('touchFlags',DWORD),('touchMask',DWORD),
              ('rcContact',RECT),('rcContactRaw',RECT),('orientation',DWORD),('pressure',DWORD)]

def validate_events(events):
    if not isinstance(events,list) or len(events)>40:raise ValueError('Pacote de toque inválido')
    result=[]
    for event in events:
        if not isinstance(event,dict):raise ValueError('Evento inválido')
        ident=event.get('id');action=event.get('a');x=event.get('x');y=event.get('y')
        if isinstance(ident,bool) or not isinstance(ident,int) or not 0<=ident<10:raise ValueError('Dedo inválido')
        if action not in ('down','move','up','cancel','hold'):raise ValueError('Ação inválida')
        if any(isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) or not 0<=v<=1 for v in (x,y)):raise ValueError('Coordenadas inválidas')
        result.append(dict(id=ident,a=action,x=x,y=y))
    return result

class TouchScreen:
    def __init__(self,api=None):
        self.api=api or C.WinDLL('user32',use_last_error=True)
        if api is None:
            self.api.InitializeTouchInjection.argtypes=[DWORD,DWORD];self.api.InitializeTouchInjection.restype=C.c_bool
            self.api.InjectTouchInput.argtypes=[DWORD,C.POINTER(POINTER_TOUCH_INFO)];self.api.InjectTouchInput.restype=C.c_bool
        if not self.api.InitializeTouchInjection(10,1):raise RuntimeError('O Windows não permitiu inicializar a tela touch')
        self.contacts={};self.rect={'left':0,'top':0,'width':1,'height':1};self.lock=threading.RLock();self.last=time.monotonic()

    def set_monitor(self,rect):
        with self.lock:
            if self.contacts:self.neutral()
            self.rect=dict(rect)

    def position(self,x,y):
        return self.rect['left']+round(x*(self.rect['width']-1)),self.rect['top']+round(y*(self.rect['height']-1))

    def inject(self,special_id=None,special_flags=None):
        values=[]
        for ident,(x,y) in sorted(self.contacts.items()):
            info=POINTER_TOUCH_INFO();info.pointerInfo.pointerType=2;info.pointerInfo.pointerId=ident+1
            info.pointerInfo.pointerFlags=special_flags if ident==special_id else UPDATE|CONTACT|INRANGE
            info.pointerInfo.ptPixelLocation=POINT(x,y);info.pointerInfo.ptPixelLocationRaw=POINT(x,y)
            info.touchMask=1|4;info.rcContact=RECT(x-2,y-2,x+2,y+2);info.pressure=512
            values.append(info)
        if values:
            frame=(POINTER_TOUCH_INFO*len(values))(*values)
            if not self.api.InjectTouchInput(len(values),frame):
                raise RuntimeError('O Windows recusou o toque. Confira o aplicativo de destino e suas permissões.')

    def events(self,events):
        events=validate_events(events)
        with self.lock:
            moved=False
            for event in events:
                ident=event['id'];action=event['a'];position=self.position(event['x'],event['y'])
                if action in ('move','hold'):
                    if ident in self.contacts:self.contacts[ident]=position;moved=True
                    continue
                if moved:self.inject();moved=False
                if action=='down':
                    if ident in self.contacts:continue
                    self.contacts[ident]=position;self.inject(ident,DOWN|CONTACT|INRANGE)
                elif ident in self.contacts:
                    if action in ('up','cancel'):
                        # Windows requires terminal coordinates to match the preceding update.
                        if self.contacts[ident]!=position:
                            self.contacts[ident]=position;self.inject()
                        self.inject(ident,UP|(CANCELED if action=='cancel' else 0));del self.contacts[ident]
            if moved:self.inject()
            self.last=time.monotonic()

    def neutral(self):
        with self.lock:
            try:
                for ident in list(self.contacts):
                    self.inject(ident,UP|CANCELED);del self.contacts[ident]
            except (RuntimeError,OSError):logging.exception('Touch cancellation refused by Windows')
            finally:self.contacts.clear();self.last=time.monotonic()

    def expire(self):
        if self.contacts and time.monotonic()-self.last>0.8:self.neutral()
