"""Generate simple original gamepad icon and opaque legacy launch images."""
from pathlib import Path
import struct
import zlib

ROOT=Path(__file__).resolve().parents[1]/'ios'/'Resources'

def png(path,width,height,launch=False):
    rows=bytearray()
    scale=min(width,height)*(0.20 if launch else 0.76)
    for y in range(height):
        rows.append(0)
        for x in range(width):
            u=(x-width/2)/scale;v=(y-height/2)/scale
            color=(16,23+int(y/height*9),33+int(y/height*11))
            body=(abs(u)<0.31 and abs(v)<0.19) or ((u-0.28)**2+(v-0.02)**2<0.18**2) or ((u+0.28)**2+(v-0.02)**2<0.18**2)
            if body:color=(76,226,188)
            if (abs(u+0.20)<0.025 and abs(v)<0.085) or (abs(u+0.20)<0.085 and abs(v)<0.025):color=(16,23,33)
            for bx,by in [(0.20,-0.08),(0.27,0),(0.13,0),(0.20,0.08)]:
                if (u-bx)**2+(v-by)**2<0.027**2:color=(16,23,33)
            rows.extend(color)
    def chunk(kind,data):return struct.pack('>I',len(data))+kind+data+struct.pack('>I',zlib.crc32(kind+data)&0xffffffff)
    path.write_bytes(b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',width,height,8,2,0,0,0))+chunk(b'IDAT',zlib.compress(rows,9))+chunk(b'IEND',b''))

if __name__=='__main__':
    ROOT.mkdir(parents=True,exist_ok=True)
    png(ROOT/'Icon-76.png',76,76);png(ROOT/'Icon-76@2x.png',152,152)
    png(ROOT/'LaunchPortrait.png',768,1024,True);png(ROOT/'LaunchLandscape.png',1024,768,True)
