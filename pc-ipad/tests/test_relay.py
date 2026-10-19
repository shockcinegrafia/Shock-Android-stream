import hashlib
import json
from pathlib import Path
import secrets
import socket
import ssl
import sys
import tempfile
import threading
import unittest
from unittest.mock import Mock,patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'windows'))
from host import Host
from protocol import MAGIC,CLIENT_INFO,INFO,VIDEO,TOUCH,BYE,packet,proof,read_exact,read_packet
from remote import RemoteIdentity,pinned_client
from relay_client import parse_setup,pairing,invitation,send_request,read_line,Tunnel,revoke_pairing
from relay_test_support import RelayServer


class RelayTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.pc=RemoteIdentity(Path(self.temp.name)/'pc');self.relay=RemoteIdentity(Path(self.temp.name)/'relay')
        self.owner=secrets.token_hex(32);self.server=RelayServer(self.relay,self.owner);self.addCleanup(self.server.close)
        self.setup=f'shockrelay://127.0.0.1:{self.server.port}?cert={self.relay.fingerprint}&owner={self.owner}'

    def outer(self):
        result=pinned_client(socket.create_connection(('127.0.0.1',self.server.port),timeout=3),self.relay.fingerprint)
        self.addCleanup(result.close);return result

    def request(self,sock,op,route='a'*32,ticket='b'*64,owner=None):
        value={'v':1,'op':op,'route':route,'ticket':ticket}
        if owner is not None:value['owner']=owner
        send_request(sock,value)

    def test_setup_validation_and_client_invitation_excludes_owner_secret(self):
        self.assertEqual(parse_setup(self.setup),( '127.0.0.1',self.server.port,self.relay.fingerprint,self.owner))
        text=invitation(self.pc,self.setup)
        self.assertNotIn(self.owner,text);self.assertIn(self.pc.key,text);self.assertIn('relaycert=',text)
        self.assertEqual(pairing(self.pc),pairing(RemoteIdentity(self.pc.directory)))
        for text in (self.setup+'&owner='+self.owner,self.setup.replace('shockrelay:','http:'),self.setup.replace(self.owner,'123456')):
            with self.assertRaises(ValueError):parse_setup(text)

    def test_unauthorized_owner_unknown_route_and_bad_ticket_are_refused(self):
        for op,owner in (('host','0'*64),('join',None)):
            connection=self.outer();self.request(connection,op,owner=owner)
            self.assertEqual(read_line(connection),b'DENIED');connection.close()
        host=self.outer();self.request(host,'host',owner=self.owner);self.assertEqual(read_line(host),b'WAIT')
        client=self.outer();self.request(client,'join',ticket='0'*64);self.assertEqual(read_line(client),b'DENIED')
        self.assertFalse(self.server.relay.routes['a'*32].joined.is_set());host.close()

    def test_duplicate_host_registration_cannot_replace_waiting_pc(self):
        first=self.outer();self.request(first,'host',owner=self.owner);self.assertEqual(read_line(first),b'WAIT')
        duplicate=self.outer();self.request(duplicate,'host',owner=self.owner);self.assertEqual(read_line(duplicate),b'BUSY')
        first.close();duplicate.close()

    def test_heartbeat_is_drained_before_join_enters_inner_tls(self):
        self.server.relay.heartbeat=.03
        host=self.outer();self.request(host,'host',owner=self.owner);self.assertEqual(read_line(host),b'WAIT')
        self.assertEqual(read_line(host),b'ALIVE')
        client=self.outer();self.request(client,'join');host.sendall(b'P')
        self.assertEqual(read_line(host),b'READY');self.assertEqual(read_line(client),b'READY')
        sample=b'inner TLS fixture';host.sendall(sample);self.assertEqual(read_exact(client,len(sample)),sample)

    def test_unresponsive_registered_host_is_expired_for_reconnection(self):
        self.server.relay.heartbeat=.03;self.server.relay.heartbeat_timeout=.05
        host=self.outer();self.request(host,'host',owner=self.owner);self.assertEqual(read_line(host),b'WAIT')
        self.assertEqual(read_line(host),b'ALIVE');self.assertEqual(read_line(host),b'DENIED')
        self.assertNotIn('a'*32,self.server.relay.routes)

    def test_malformed_and_oversized_requests_are_bounded(self):
        for payload in (b'[]\n',b'{}\n',b'x'*1100+b'\n'):
            connection=self.outer();connection.sendall(payload)
            self.assertEqual(read_line(connection),b'DENIED');connection.close()

    def host(self):
        host=Host(lambda _:None,{'hostId':'a'*32,'pin':'123456'})
        host.pad=Mock();host.input_mode='touch';host.monitor=None;host.video_params=(20,1024,'economy');host.remote_audio=False
        host.thread=threading.Thread(target=host.stop_event.wait,daemon=True);host.thread.start()
        def cleanup():
            host.stop()
            for worker in host.workers:worker.join(5)
        self.addCleanup(cleanup);return host

    def connect_inner(self):
        pair=pairing(self.pc);outer=self.outer();self.request(outer,'join',pair['route'],pair['ticket'])
        self.assertEqual(read_line(outer),b'READY');tunnel=Tunnel(outer);self.addCleanup(tunnel.close)
        inner=pinned_client(tunnel.local,self.pc.fingerprint);self.addCleanup(inner.close);return inner

    def test_full_host_relay_client_auth_video_and_touch(self):
        host=self.host();data=bytes(range(256))*4096;received=[];finished=threading.Event()
        def session(connection,*args,**kwargs):
            instance=Mock()
            def run():
                try:
                    for _ in range(6):
                        connection.sendall(packet(VIDEO,data));received.append(read_packet(connection))
                finally:finished.set()
            instance.run.side_effect=run;return instance
        with patch('host.Session',side_effect=session):
            host.enable_relay(self.pc,self.setup)
            self.assertTrue(self.server.wait_route(pairing(self.pc)['route']))
            client=self.connect_inner();challenge=read_exact(client,38);self.assertEqual(challenge[:6],MAGIC)
            client.sendall(proof(self.pc.key,challenge[6:]));self.assertEqual(read_exact(client,1),b'\x01')
            client.sendall(packet(CLIENT_INFO,b'{"width":1024,"height":768}'))
            digest=hashlib.sha256(data).digest()
            for _ in range(6):
                self.assertEqual(read_packet(client),(VIDEO,data));client.sendall(packet(TOUCH,digest))
            self.assertTrue(finished.wait(4));self.assertEqual(received,[(TOUCH,digest)]*6)
            self.assertGreater(self.server.relay.transferred,len(data)*6)

    def test_disabled_relay_cannot_start_late_session(self):
        host=self.host();guard=threading.Event();host.relay_stop=guard;guard.set();host.authenticate=Mock()
        host.run_connection(Mock(),20,1024,False,'relay',self.pc.key,relay_guard=guard)
        host.authenticate.assert_not_called();self.assertFalse(host.active_lock.locked())

    def test_relay_cannot_impersonate_pc_certificate(self):
        host=self.host();host.enable_relay(self.pc,self.setup)
        self.assertTrue(self.server.wait_route(pairing(self.pc)['route']))
        pair=pairing(self.pc);outer=self.outer();self.request(outer,'join',pair['route'],pair['ticket'])
        self.assertEqual(read_line(outer),b'READY');tunnel=Tunnel(outer);self.addCleanup(tunnel.close)
        # Trusting the outside relay certificate must not authorize it as the inside PC.
        with self.assertRaises(ssl.SSLCertVerificationError):pinned_client(tunnel.local,self.relay.fingerprint)

    def test_revocation_changes_rendezvous_and_reconnects_without_local_listener(self):
        old=pairing(self.pc);revoke_pairing(self.pc);new=pairing(self.pc)
        self.assertNotEqual(old['route'],new['route']);self.assertNotEqual(old['ticket'],new['ticket'])
        host=self.host()
        def session(connection,*args,**kwargs):
            result=Mock()
            def run():
                connection.sendall(packet(INFO,b'authenticated'))
                self.assertEqual(read_packet(connection),(BYE,b''))
            result.run.side_effect=run;return result
        with patch('host.Session',side_effect=session):
            host.enable_relay(self.pc,self.setup)
            for _ in range(2):
                self.assertTrue(self.server.wait_route(new['route']))
                client=self.connect_inner();challenge=read_exact(client,38)
                client.sendall(proof(self.pc.key,challenge[6:]));self.assertEqual(read_exact(client,1),b'\x01')
                client.sendall(packet(CLIENT_INFO,b'{"width":1024,"height":768}'))
                self.assertEqual(read_packet(client),(INFO,b'authenticated'));client.sendall(packet(BYE));client.close()
            self.assertIsNone(host.listener);self.assertIsNone(host.remote_listener)


if __name__=='__main__':unittest.main()
