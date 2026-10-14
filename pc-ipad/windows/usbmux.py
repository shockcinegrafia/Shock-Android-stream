"""Apple USB multiplexing client; replaces a separately launched iproxy process."""
import plistlib
import socket
import struct
from protocol import read_exact

HEADER=struct.Struct('<IIII')
SERVICE=('127.0.0.1',27015)

def exchange(sock,message,tag=1):
    body=plistlib.dumps({'ClientVersionString':'ShockStream-0.2','ProgName':'ShockStream',**message},fmt=plistlib.FMT_XML)
    sock.sendall(HEADER.pack(16+len(body),1,8,tag)+body)
    length,version,kind,response_tag=HEADER.unpack(read_exact(sock,16))
    if length<16 or length>1024*1024 or version!=1 or kind!=8 or response_tag!=tag:
        raise ValueError('Resposta USB da Apple inválida')
    return plistlib.loads(read_exact(sock,length-16))

def list_devices(service=SERVICE):
    try:
        with socket.create_connection(service,timeout=2) as sock:
            reply=exchange(sock,{'MessageType':'ListDevices'})
        devices=reply.get('DeviceList',[])
        return [d for d in devices if d.get('Properties',{}).get('ConnectionType','USB')=='USB']
    except OSError as error:
        raise RuntimeError('Suporte USB Apple indisponível. Use Preparar USB Apple, conecte o cabo e confirme Confiar no iPad.') from error

def connect_device(device_id,port=8091,service=SERVICE):
    sock=socket.create_connection(service,timeout=3)
    try:
        result=exchange(sock,{'MessageType':'Connect','DeviceID':int(device_id),'PortNumber':socket.htons(port)})
        code=result.get('Number',-1)
        if code!=0:
            raise ConnectionError('Abra o modo USB no app do iPad e toque Aguardar PC. Resposta USB: '+str(code))
        sock.settimeout(5)
        return sock  # The same socket is now the bidirectional USB data tunnel.
    except Exception:
        sock.close();raise
