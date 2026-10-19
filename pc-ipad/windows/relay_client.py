"""Outbound-only relay registration. The existing streaming protocol stays inside PC/iPad TLS."""
import json
import secrets
import socket
import threading
import time
from urllib.parse import urlsplit,parse_qs

from remote import endpoint,HEX64,pinned_client
_pair_lock=threading.Lock()


def parse_setup(value):
    if not isinstance(value,str) or len(value)>1024:raise ValueError('Configuração do servidor inválida')
    parsed=urlsplit(value.strip())
    if parsed.scheme!='shockrelay' or parsed.path or parsed.fragment:raise ValueError('Cole a configuração shockrelay:// fornecida pelo administrador do servidor')
    host,port=endpoint(parsed.netloc);query=parse_qs(parsed.query,strict_parsing=True)
    if set(query)!={'cert','owner'} or any(len(v)!=1 or not HEX64.fullmatch(v[0]) for v in query.values()):raise ValueError('Configuração do servidor inválida')
    return host,port,query['cert'][0],query['owner'][0]


def pairing(identity):
    with _pair_lock:return _pairing(identity)


def _pairing(identity):
    path=identity.directory/'relay-pairing.json'
    if path.exists():
        value=json.loads(path.read_text(encoding='utf-8'))
        if (not isinstance(value,dict) or not isinstance(value.get('route'),str) or len(value['route'])!=32 or
            any(c not in '0123456789abcdef' for c in value['route']) or
            not isinstance(value.get('ticket'),str) or not HEX64.fullmatch(value['ticket'])):raise ValueError('Pareamento remoto inválido')
        return value
    value={'route':secrets.token_hex(16),'ticket':secrets.token_hex(32)}
    with path.open('x',encoding='utf-8') as file:json.dump(value,file)
    path.chmod(0o600);return value


def revoke_pairing(identity):
    with _pair_lock:
        value={'route':secrets.token_hex(16),'ticket':secrets.token_hex(32)}
        path=identity.directory/'relay-pairing.json';temporary=path.with_suffix('.tmp')
        temporary.write_text(json.dumps(value),encoding='utf-8');temporary.chmod(0o600);temporary.replace(path)


def invitation(identity, setup):
    host,port,cert,_=parse_setup(setup);pair=pairing(identity)
    if ':' in host:host='['+host+']'
    return (f'shockstream-relay://{host}:{port}?key={identity.key}&cert={identity.fingerprint}'
            f'&relaycert={cert}&route={pair["route"]}&ticket={pair["ticket"]}')


def send_request(connection,value):
    payload=json.dumps(value,separators=(',',':')).encode()+b'\n'
    if len(payload)>1024:raise ValueError('Relay request too large')
    connection.sendall(payload)


def read_line(connection, stop=None):
    result=bytearray();deadline=time.monotonic()+40
    while len(result)<64:
        if stop and stop.is_set():raise ConnectionError('Relay stopped')
        try:data=connection.recv(1)
        except socket.timeout:
            if stop and time.monotonic()<deadline:continue
            raise
        if not data:raise ConnectionError('Relay closed')
        if data==b'\n':return bytes(result)
        result.extend(data)
    raise ValueError('Invalid relay response')


class Tunnel:
    """Bounded byte forwarding, no video decoding or custom cryptography."""
    def __init__(self, upstream):
        self.upstream=upstream;self.local,self.bridge=socket.socketpair();self.closed=threading.Event()
        self.threads=[]
        upstream.settimeout(3);self.bridge.settimeout(3)
        for source,target in ((upstream,self.bridge),(self.bridge,upstream)):
            thread=threading.Thread(target=self.pump,args=(source,target),daemon=True)
            self.threads.append(thread);thread.start()

    def pump(self,source,target):
        try:
            while not self.closed.is_set():
                try:data=source.recv(16384)
                except socket.timeout:continue
                if not data:break
                target.sendall(data)
        except (ConnectionError,OSError):pass
        finally:self.close()

    def close(self):
        self.closed.set()
        for sock in (self.upstream,self.bridge):
            try:sock.shutdown(socket.SHUT_RDWR)
            except OSError:pass
            sock.close()


def run(host,identity,setup,stop):
    address,port,fingerprint,owner=parse_setup(setup);pair=pairing(identity)
    delay=1
    while not stop.is_set() and not host.stop_event.is_set():
        connection=None;tunnel=None
        try:
            raw=socket.create_connection((address,port),timeout=5)
            host.relay_socket=raw
            connection=pinned_client(raw,fingerprint);host.relay_socket=connection
            send_request(connection,{'v':1,'op':'host','route':pair['route'],'ticket':pair['ticket'],'owner':owner})
            if read_line(connection)!=b'WAIT':raise ConnectionError('Relay refused registration')
            host.report('Internet: PC disponível no servidor; aguardando iPad.');delay=1
            connection.settimeout(1)
            while not stop.is_set():
                status=read_line(connection,stop)
                if status==b'ALIVE':connection.sendall(b'P');continue
                if status!=b'READY':raise ConnectionError('Invalid relay readiness')
                break
            if stop.is_set():break
            tunnel=Tunnel(connection)
            tunnel.local.settimeout(8)
            # The relay terminates only the outside TLS. This second TLS session terminates at the PC.
            secured=identity.context.wrap_socket(tunnel.local,server_side=True)
            fps,size,_=host.video_params
            host.run_connection(secured,fps,size,host.remote_audio,'internet protegida',identity.key,relay_guard=stop)
        except Exception:
            if not stop.is_set() and not host.stop_event.is_set():host.report('Internet: servidor indisponível ou conexão encerrada; reconectando automaticamente.')
        finally:
            if tunnel:tunnel.close();tunnel.local.close()
            if connection:connection.close()
            host.relay_socket=None
        stop.wait(delay);delay=min(15,delay*2)
