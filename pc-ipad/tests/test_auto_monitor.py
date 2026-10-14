import json
from pathlib import Path
import socket
import sys
import tempfile
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'windows'))
import host
from discovery import service_info
from protocol import ACK, BYE, CLIENT_INFO, INFO, VIDEO, MAGIC, packet, proof, read_exact, read_packet, validate_display
from settings import load_settings

IDENTITY = {'hostId':'1'*32, 'pin':'123456'}


class PairingTests(unittest.TestCase):
    def test_identity_survives_relaunch_and_does_not_advertise_pin(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'settings.json'
            first = load_settings(path)
            self.assertEqual(first, load_settings(path))
        info = service_info(first['hostId'], 8090, ['192.168.1.3'])
        self.assertEqual(info.properties[b'hostId'].decode(), first['hostId'])
        self.assertNotIn(b'pin', info.properties)
        self.assertNotIn(first['pin'].encode(), info.text)
        self.assertEqual(info.parsed_addresses(), ['192.168.1.3'])

    def test_authenticated_orientation_and_wrong_pin(self):
        for pin, accepted in [('123456', True), ('654321', False)]:
            server, client = socket.socketpair()
            result, errors = [], []
            def authenticate():
                try:result.append(host.Host(lambda _:None, IDENTITY).authenticate(server))
                except Exception as exc:errors.append(exc)
                finally:server.close()
            worker = threading.Thread(target=authenticate);worker.start()
            challenge = read_exact(client, 38)
            self.assertEqual(challenge[:6], MAGIC)
            client.sendall(proof(pin, challenge[6:]))
            self.assertEqual(read_exact(client, 1), b'\x01' if accepted else b'\x00')
            if accepted:client.sendall(packet(CLIENT_INFO,b'{"width":768,"height":1024}'))
            worker.join(3);client.close()
            self.assertFalse(worker.is_alive())
            if accepted:self.assertEqual(result, [(768,1024)])
            else:self.assertIsInstance(errors[0], PermissionError)

    def test_second_transport_cannot_release_active_touch(self):
        owner = host.Host(lambda _:None, IDENTITY)
        owner.pad = Mock()
        owner.active_lock.acquire()
        contender = Mock()
        owner.run_connection(contender,30,1024,False,'USB')
        contender.close.assert_called_once()
        owner.pad.neutral.assert_not_called()
        owner.active_lock.release()

    def test_wifi_touch_never_creates_gamepad(self):
        owner = host.Host(lambda _:None, IDENTITY)
        touch = Mock()
        with patch('touchscreen.TouchScreen',return_value=touch), patch.object(host,'XboxPad',side_effect=AssertionError('gamepad forbidden')), patch('discovery.Advertiser'), patch.object(owner,'serve'):
            owner.start(port=0, mode='wifi', input_mode='touch')
            owner.thread.join(2)
            self.assertIs(owner.pad,touch)
            owner.stop()


class RotationSessionTests(unittest.TestCase):
    def test_orientation_restarts_encoder_with_new_sps_and_info(self):
        import av
        import numpy as np
        server, client = socket.socketpair();server.settimeout(3);client.settimeout(3)
        touch = SimpleNamespace(neutral=Mock(), expire=lambda:None, events=Mock())
        session = host.Session(server,touch,30,1024,False,lambda _:None,'touch',host_id=IDENTITY['hostId'])
        def capture():
            while not session.stop.is_set():
                with session.display_lock:width,height=session.client_size
                session.latest.put((np.zeros((height,width,4),dtype=np.uint8),width,height,(width,height)))
                session.stop.wait(0.02)
        session.capture = capture
        errors=[]
        def run():
            try:session.run()
            except Exception as exc:errors.append(exc)
        worker=threading.Thread(target=run);worker.start()
        try:
            kind,body=read_packet(client);self.assertEqual(kind,INFO)
            info=json.loads(body);self.assertEqual((info['width'],info['height']),(1024,768))
            self.assertEqual(info['mode'],'touch');self.assertEqual(info['hostId'],IDENTITY['hostId'])
            self.assertEqual(read_packet(client)[0],VIDEO)
            client.sendall(packet(CLIENT_INFO,b'{"width":768,"height":1024,"displayId":2}'))
            client.sendall(packet(ACK))
            for _ in range(10):
                kind,body=read_packet(client)
                if kind==INFO:break
                self.assertEqual(kind,VIDEO);client.sendall(packet(ACK))
            self.assertEqual(kind,INFO)
            info=json.loads(body);self.assertEqual((info['width'],info['height']),(768,1024))
            self.assertEqual(info['displayId'],2)
            kind,body=read_packet(client);self.assertEqual(kind,VIDEO)
            frames=av.CodecContext.create('h264','r').decode(av.Packet(body))
            self.assertEqual((frames[0].width,frames[0].height),(768,1024))
            client.sendall(packet(BYE));worker.join(4)
            self.assertFalse(worker.is_alive());self.assertFalse(errors)
            touch.neutral.assert_called()
        finally:
            session.close();client.close();worker.join(4)

    def test_native_panel_validation(self):
        self.assertEqual(validate_display({'width':1024,'height':768}),(1024,768))
        for value in ({'width':1920,'height':1080},{'width':True,'height':1024},[],{'width':768.0,'height':1024}):
            with self.assertRaises(ValueError):validate_display(value)

    def test_rotation_during_encoder_setup_does_not_confirm_old_viewport(self):
        import numpy as np
        server,client=socket.socketpair();server.settimeout(3);client.settimeout(3)
        touch=SimpleNamespace(neutral=Mock(),expire=lambda:None)
        session=host.Session(server,touch,30,1024,False,lambda _:None,'touch')
        def capture():
            while not session.stop.is_set():
                with session.display_lock:
                    target=session.client_size;generation=session.display_generation
                session.latest.put((np.zeros((target[1],target[0],4),dtype=np.uint8),*target,target,generation))
                session.stop.wait(0.01)
        session.capture=capture
        real_encoder=host.make_encoder;calls=[];errors=[]
        def encoder(width,height,fps):
            if not calls:
                session.display_preferences(b'{"width":768,"height":1024,"displayId":7}')
            calls.append((width,height))
            return real_encoder(width,height,fps)
        def run():
            try:session.run()
            except Exception as exc:errors.append(exc)
        with patch.object(host,'make_encoder',side_effect=encoder):
            worker=threading.Thread(target=run);worker.start()
            try:
                kind,body=read_packet(client);self.assertEqual(kind,INFO)
                info=json.loads(body)
                self.assertEqual((info['width'],info['height'],info['displayId']),(768,1024,7))
                self.assertEqual(read_packet(client)[0],VIDEO)
                client.sendall(packet(BYE));worker.join(4)
                self.assertFalse(worker.is_alive());self.assertFalse(errors)
                self.assertEqual(calls[:2],[(1024,768),(768,1024)])
            finally:session.close();client.close();worker.join(4)


class ApplePreparationTests(unittest.TestCase):
    def test_ready_service_without_device_does_not_reinstall(self):
        from setup_manager import prepare_apple_usb
        with patch('usbmux.diagnostics',return_value={'status':'no_device','message':'Conecte o cabo.'}),patch('setup_manager.subprocess.run') as install:
            self.assertEqual(prepare_apple_usb(),'Conecte o cabo.')
            install.assert_not_called()

    def test_installed_service_is_rechecked(self):
        from setup_manager import prepare_apple_usb
        responses=[{'status':'service_unavailable','message':'offline'}, {'status':'ready','message':'iPad encontrado.'}]
        with patch('usbmux.diagnostics',side_effect=responses),patch('setup_manager.subprocess.run',return_value=SimpleNamespace(returncode=0)):
            self.assertEqual(prepare_apple_usb(),'iPad encontrado.')


if __name__=='__main__':unittest.main()
