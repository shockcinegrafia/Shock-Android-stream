"""Composite the Windows cursor into a small BGRA tile, without moving it."""
import ctypes as C

U32=C.c_uint32;I32=C.c_int32;U16=C.c_uint16;HANDLE=C.c_void_p
class POINT(C.Structure):_fields_=[('x',I32),('y',I32)]
class CURSORINFO(C.Structure):_fields_=[('cbSize',U32),('flags',U32),('hCursor',HANDLE),('ptScreenPos',POINT)]
class ICONINFO(C.Structure):_fields_=[('fIcon',I32),('xHotspot',U32),('yHotspot',U32),('hbmMask',HANDLE),('hbmColor',HANDLE)]
class BITMAP(C.Structure):
    _fields_=[('bmType',I32),('bmWidth',I32),('bmHeight',I32),('bmWidthBytes',I32),('bmPlanes',U16),('bmBitsPixel',U16),('bmBits',HANDLE)]
class BITMAPINFOHEADER(C.Structure):
    _fields_=[('biSize',U32),('biWidth',I32),('biHeight',I32),('biPlanes',U16),('biBitCount',U16),
              ('biCompression',U32),('biSizeImage',U32),('biXPelsPerMeter',I32),('biYPelsPerMeter',I32),('biClrUsed',U32),('biClrImportant',U32)]
class BITMAPINFO(C.Structure):_fields_=[('header',BITMAPINFOHEADER),('colors',U32*1)]

def clipped_cursor(monitor,x,y,hotx,hoty,width,height):
    x-=monitor['left']+hotx;y-=monitor['top']+hoty
    left=max(0,x);top=max(0,y);right=min(monitor['width'],x+width);bottom=min(monitor['height'],y+height)
    return (left,top,right,bottom,x-left,y-top) if right>left and bottom>top else None

class CursorRenderer:
    def __init__(self):
        self.user=C.WinDLL('user32',use_last_error=True);self.gdi=C.WinDLL('gdi32',use_last_error=True)
        signatures=[(self.user,'GetCursorInfo',[C.POINTER(CURSORINFO)],I32),
                    (self.user,'CopyIcon',[HANDLE],HANDLE),(self.user,'DestroyIcon',[HANDLE],I32),
                    (self.user,'GetIconInfo',[HANDLE,C.POINTER(ICONINFO)],I32),
                    (self.user,'DrawIconEx',[HANDLE,I32,I32,HANDLE,I32,I32,U32,HANDLE,U32],I32),
                    (self.gdi,'GetObjectW',[HANDLE,I32,HANDLE],I32),
                    (self.gdi,'CreateCompatibleDC',[HANDLE],HANDLE),(self.gdi,'DeleteDC',[HANDLE],I32),
                    (self.gdi,'CreateDIBSection',[HANDLE,C.POINTER(BITMAPINFO),U32,C.POINTER(HANDLE),HANDLE,U32],HANDLE),
                    (self.gdi,'SelectObject',[HANDLE,HANDLE],HANDLE),(self.gdi,'DeleteObject',[HANDLE],I32),
                    (self.gdi,'GdiFlush',[],I32)]
        for dll,name,args,result in signatures:
            function=getattr(dll,name);function.argtypes=args;function.restype=result
        self.dc=self.gdi.CreateCompatibleDC(None);self.bitmap=None;self.original=None;self.pixels=HANDLE();self.size=None
        if not self.dc:raise OSError('Could not create cursor capture DC')

    def close(self):
        if self.bitmap:
            self.gdi.SelectObject(self.dc,self.original);self.gdi.DeleteObject(self.bitmap)
            self.bitmap=None;self.size=None;self.pixels=HANDLE()
        if self.dc:self.gdi.DeleteDC(self.dc);self.dc=None

    def _surface(self,width,height):
        if self.size==(width,height):return
        if self.bitmap:
            self.gdi.SelectObject(self.dc,self.original);self.gdi.DeleteObject(self.bitmap);self.bitmap=None;self.size=None
        info=BITMAPINFO();info.header=BITMAPINFOHEADER(C.sizeof(BITMAPINFOHEADER),width,-height,1,32,0,width*height*4,0,0,0,0)
        self.bitmap=self.gdi.CreateDIBSection(self.dc,C.byref(info),0,C.byref(self.pixels),None,0)
        if not self.bitmap:raise OSError('Could not allocate cursor tile')
        self.original=self.gdi.SelectObject(self.dc,self.bitmap)
        if not self.original or self.original==C.c_void_p(-1).value:
            self.gdi.DeleteObject(self.bitmap);self.bitmap=None;raise OSError('Could not select cursor tile')
        self.size=(width,height)

    def draw_icon(self,image,monitor,icon,x,y):
        """Draw a supplied native icon at a global hotspot (also used by tests)."""
        import numpy as np
        info=ICONINFO()
        if not self.user.GetIconInfo(icon,C.byref(info)):raise OSError('Cursor metadata unavailable')
        try:
            bitmap=BITMAP();handle=info.hbmColor or info.hbmMask
            if not self.gdi.GetObjectW(handle,C.sizeof(bitmap),C.byref(bitmap)):raise OSError('Cursor bitmap unavailable')
            width=bitmap.bmWidth;height=abs(bitmap.bmHeight)//(1 if info.hbmColor else 2)
            if not 0<width<=1024 or not 0<height<=1024:return False
            clipped=clipped_cursor(monitor,x,y,info.xHotspot,info.yHotspot,width,height)
            if not clipped:return False
            left,top,right,bottom,drawx,drawy=clipped;w=right-left;h=bottom-top
            self._surface(w,h)
            tile=np.ascontiguousarray(image[top:bottom,left:right])
            C.memmove(self.pixels,int(tile.ctypes.data),tile.nbytes)
            if not self.user.DrawIconEx(self.dc,drawx,drawy,icon,0,0,0,None,3):raise OSError('Cursor draw refused')
            if not self.gdi.GdiFlush():raise OSError('Cursor drawing not completed')
            pixels=(C.c_uint8*(w*h*4)).from_address(self.pixels.value)
            image[top:bottom,left:right]=np.ctypeslib.as_array(pixels).reshape(h,w,4)
            return True
        finally:
            if info.hbmColor:self.gdi.DeleteObject(info.hbmColor)
            if info.hbmMask:self.gdi.DeleteObject(info.hbmMask)

    def apply(self,image,monitor):
        info=CURSORINFO();info.cbSize=C.sizeof(info)
        if not self.user.GetCursorInfo(C.byref(info)):raise OSError('Global cursor unavailable')
        # Respect cursors hidden by the application or suppressed during touch.
        if not info.flags&1 or info.flags&2 or not info.hCursor:return False
        icon=self.user.CopyIcon(info.hCursor)
        if not icon:raise OSError('Could not snapshot cursor')
        try:return self.draw_icon(image,monitor,icon,info.ptScreenPos.x,info.ptScreenPos.y)
        finally:self.user.DestroyIcon(icon)
