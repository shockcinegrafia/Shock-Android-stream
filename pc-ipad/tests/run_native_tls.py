"""Exercise the real Apple SecureTransport client against the Windows Python TLS context."""
import socket
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'windows'))
from remote import RemoteIdentity
from protocol import read_exact
from tls_channel import TLSChannel

with tempfile.TemporaryDirectory() as directory:
    identity=RemoteIdentity(directory)
    for correct in (True,False):
        listener=socket.socket();listener.bind(('127.0.0.1',0));listener.listen(1);listener.settimeout(20)
        errors=[]
        def serve():
            try:
                raw,_=listener.accept();raw.settimeout(12)
                with raw:
                    with TLSChannel(identity.context.wrap_socket(raw,server_side=True)) as secured:
                        if correct:
                            data=bytes(i%251 for i in range(1024*1024))
                            # Server sends video while receiving controls in the opposite direction.
                            def send():
                                try:secured.sendall(data)
                                except Exception as exc:errors.append(exc)
                            sender=threading.Thread(target=send);sender.start()
                            for i in range(200):assert read_exact(secured,4)==i.to_bytes(4,'big')
                            sender.join(15);assert not sender.is_alive()
                            assert read_exact(secured,1)==b'\xa5'
                            secured.sendall(b'\x5a')
            except Exception as exc:
                if correct:errors.append(exc)
        server=threading.Thread(target=serve);server.start()
        result=subprocess.run([sys.argv[1],str(listener.getsockname()[1]),identity.fingerprint if correct else '0'*64,str(int(correct))],timeout=30)
        server.join(15);listener.close()
        assert result.returncode==0,(correct,result.returncode,[type(e).__name__+': '+str(e) for e in errors])
        assert not server.is_alive() and not errors,errors
