"""Run native Apple nested TLS against the real relay and outbound Windows transport."""
from pathlib import Path
import secrets
import subprocess
import sys
import tempfile
import threading

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'windows'))
from remote import RemoteIdentity
from relay_client import run,pairing,revoke_pairing
from protocol import read_exact
from relay_test_support import RelayServer

with tempfile.TemporaryDirectory() as directory:
    relay_identity=RemoteIdentity(Path(directory)/'relay');pc=RemoteIdentity(Path(directory)/'pc');owner=secrets.token_hex(32)
    server=RelayServer(relay_identity,owner)
    try:
        for mode in ('valid','wrong-relay','wrong-pc'):
            revoke_pairing(pc)
            completed=threading.Event();errors=[]
            class NativeHost:
                stop_event=threading.Event();video_params=(20,1024,'economy');remote_audio=False;relay_socket=None
                def report(self,text):pass
                def run_connection(self,connection,*args,**kwargs):
                    try:
                        data=bytes(i%251 for i in range(1024*1024))
                        sender=threading.Thread(target=lambda:connection.sendall(data));sender.start()
                        for i in range(200):assert read_exact(connection,4)==i.to_bytes(4,'big')
                        sender.join(15);assert not sender.is_alive()
                        assert read_exact(connection,1)==b'\xa5' # Keep the tunnel alive until the receiver consumed the last video byte.
                        connection.sendall(b'\x5a');completed.set()
                        try:connection.recv(1) # Keep the bridge open until the client has consumed the confirmation.
                        except OSError:pass
                    except Exception as exc:errors.append(exc)
                    finally:connection.close()
            host=NativeHost();stop=threading.Event()
            setup=f'shockrelay://127.0.0.1:{server.port}?cert={relay_identity.fingerprint}&owner={owner}'
            worker=threading.Thread(target=run,args=(host,pc,setup,stop),daemon=True);worker.start()
            pair=pairing(pc)
            try:
                assert server.wait_route(pair['route'])
                result=subprocess.run([sys.argv[1],str(server.port),relay_identity.fingerprint if mode!='wrong-relay' else '0'*64,
                    str(int(mode=='valid')),pc.fingerprint if mode!='wrong-pc' else '0'*64,pair['route'],pair['ticket']],timeout=30)
                assert result.returncode==0,(mode,result.returncode,[type(e).__name__+': '+str(e) for e in errors])
                if mode=='valid':assert completed.wait(5) and not errors,errors
            finally:
                stop.set();host.stop_event.set()
                if host.relay_socket:
                    import socket
                    try:host.relay_socket.shutdown(socket.SHUT_RDWR)
                    except OSError:pass
                worker.join(8);assert not worker.is_alive()
    finally:server.close()
