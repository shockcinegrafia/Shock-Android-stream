import hashlib
import socket
import ssl
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'windows'))
from remote import RemoteIdentity, endpoint, parse_invitation, pinned_client
from protocol import MAGIC, proof, read_exact, packet, CLIENT_INFO, INFO, TOUCH, BYE, read_packet
from host import Host


class RemoteTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.identity = RemoteIdentity(self.temp.name)

    def test_identity_persists_and_revocation_changes_only_access_key(self):
        other=RemoteIdentity(self.temp.name)
        self.assertEqual(other.key,self.identity.key)
        self.assertEqual(other.fingerprint,self.identity.fingerprint)
        previous=other.key;other.revoke()
        reloaded=RemoteIdentity(self.temp.name)
        self.assertNotEqual(reloaded.key,previous)
        self.assertEqual(reloaded.fingerprint,self.identity.fingerprint)

    def test_invitation_validation(self):
        for address in ('home.example:443','127.0.0.1','[::1]:8093'):
            result=parse_invitation(self.identity.invitation(address))
            self.assertEqual(result[:2],endpoint(address))
            self.assertEqual(result[2:],(self.identity.key,self.identity.fingerprint))
        for value in ('','http://home.example','a:0','a:65536','user@home','a/path','a b','a?key=x','-bad.example'):
            with self.assertRaises(ValueError,msg=value):endpoint(value)
        invitation=self.identity.invitation('home.example')
        for value in (invitation+'&key='+self.identity.key, invitation.replace('shockstream:','http:'),
                      invitation+'#x',invitation.replace(self.identity.key,'123456')):
            with self.assertRaises(ValueError):parse_invitation(value)

    def tls_pair(self, fingerprint=None):
        listener=socket.socket();listener.bind(('127.0.0.1',0));listener.listen(1)
        self.addCleanup(listener.close)
        secured=[];errors=[]
        def server():
            raw,_=listener.accept();raw.settimeout(3)
            try:secured.append(self.identity.context.wrap_socket(raw,server_side=True))
            except Exception as exc:errors.append(exc);raw.close()
        worker=threading.Thread(target=server);worker.start()
        raw=socket.create_connection(listener.getsockname(),timeout=3)
        try:client=pinned_client(raw,fingerprint or self.identity.fingerprint)
        except Exception:raw.close();worker.join(4);[s.close() for s in secured];raise
        worker.join(4)
        if errors:raise errors[0]
        self.addCleanup(client.close);self.addCleanup(secured[0].close)
        return secured[0],client

    def test_wrong_certificate_is_rejected(self):
        with self.assertRaises(ssl.SSLCertVerificationError):self.tls_pair('0'*64)

    def test_tls_authentication_and_display_then_touch(self):
        server,client=self.tls_pair()
        host=Host(lambda _:None,{'hostId':'a'*32,'pin':'123456'})
        result=[];errors=[]
        def authenticate():
            try:result.append(host.authenticate(server,self.identity.key))
            except Exception as exc:errors.append(exc)
        worker=threading.Thread(target=authenticate);worker.start()
        challenge=read_exact(client,38);self.assertEqual(challenge[:6],MAGIC)
        client.sendall(proof(self.identity.key,challenge[6:]))
        self.assertEqual(read_exact(client,1),b'\x01')
        client.sendall(packet(CLIENT_INFO,b'{"width":768,"height":1024,"displayId":12,"orientation":1}'))
        worker.join(4);self.assertFalse(worker.is_alive());self.assertFalse(errors)
        self.assertEqual(result,[(768,1024)]);self.assertEqual(host.auth_client_display_id,12)
        payload=b'[{"id":1,"a":"up","x":0.2,"y":0.7}]'
        client.sendall(packet(TOUCH,payload));self.assertEqual(read_packet(server),(TOUCH,payload))

    def test_local_pin_is_rejected_by_remote_authentication(self):
        server,client=self.tls_pair();errors=[]
        host=Host(lambda _:None,{'hostId':'a'*32,'pin':'123456'})
        def authenticate():
            try:host.authenticate(server,self.identity.key)
            except Exception as exc:errors.append(exc)
        worker=threading.Thread(target=authenticate);worker.start()
        challenge=read_exact(client,38);client.sendall(proof('123456',challenge[6:]))
        self.assertEqual(read_exact(client,1),b'\x00');worker.join(4)
        self.assertIsInstance(errors[0],PermissionError)

    def test_bidirectional_tls_large_frames(self):
        server,client=self.tls_pair();errors=[];data=bytes(range(256))*4096
        def transfer():
            try:
                for i in range(20):
                    server.sendall(packet(INFO,data))
                    self.assertEqual(read_packet(server),(TOUCH,hashlib.sha256(data).digest()))
            except Exception as exc:errors.append(exc)
        worker=threading.Thread(target=transfer);worker.start()
        for i in range(20):
            self.assertEqual(read_packet(client),(INFO,data))
            client.sendall(packet(TOUCH,hashlib.sha256(data).digest()))
        worker.join(4);self.assertFalse(worker.is_alive());self.assertFalse(errors)

    def test_disabling_remote_keeps_local_listener_and_input(self):
        host=Host(lambda _:None,{'hostId':'a'*32,'pin':'123456'})
        host.listener=Mock();host.pad=Mock();host.remote_listener=Mock();remote=host.remote_listener
        host.disable_remote();remote.close.assert_called_once()
        host.listener.close.assert_not_called();host.pad.neutral.assert_not_called()

    def test_disabled_remote_handshake_cannot_start_late_session(self):
        host=Host(lambda _:None,{'hostId':'a'*32,'pin':'123456'})
        host.pad=Mock();host.authenticate=Mock();connection=Mock();old_listener=Mock()
        host.remote_listener=Mock() # A new listener must not accept work from the old one.
        host.run_connection(connection,30,1024,False,'remota TLS',self.identity.key,old_listener)
        host.authenticate.assert_not_called();self.assertIsNone(host.session)
        self.assertFalse(host.active_lock.locked())

    def test_remote_listener_routes_authenticated_session_and_recovers_plaintext_probe(self):
        host=Host(lambda _:None,{'hostId':'a'*32,'pin':'123456'})
        host.pad=Mock();host.input_mode='touch';host.monitor=None
        host.video_params=(20,1024,'economy');host.remote_audio=False
        host.thread=threading.Thread(target=host.stop_event.wait,daemon=True);host.thread.start()
        self.addCleanup(host.stop)
        finished=threading.Event();received=[]
        def session(connection,*args,**kwargs):
            instance=Mock()
            def run():
                try:
                    connection.sendall(packet(INFO,b'{"mode":"touch"}'))
                    received.append(read_packet(connection))
                finally:finished.set()
            instance.run.side_effect=run;return instance
        with patch('host.Session',side_effect=session) as factory:
            host.enable_remote(self.identity,port=0)
            address=('127.0.0.1',host.remote_listener.getsockname()[1])
            with socket.create_connection(address,timeout=3) as probe:
                probe.sendall(b'SHOCK1-not-TLS')
                try:self.assertFalse(probe.recv(1))
                except ConnectionResetError:pass
            with pinned_client(socket.create_connection(address,timeout=3),self.identity.fingerprint) as client:
                challenge=read_exact(client,38);client.sendall(proof(self.identity.key,challenge[6:]))
                self.assertEqual(read_exact(client,1),b'\x01')
                client.sendall(packet(CLIENT_INFO,b'{"width":1024,"height":768}'))
                self.assertEqual(read_packet(client),(INFO,b'{"mode":"touch"}'))
                client.sendall(packet(BYE));self.assertTrue(finished.wait(3))
            self.assertEqual(received,[(BYE,b'')]);factory.assert_called_once()


if __name__=='__main__':unittest.main()
