import json
import socket
import sys
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'windows'))

import protocol
from protocol import (
    validate_display, display_id, display_orientation,
    packet, read_packet, CLIENT_INFO, INFO, TOUCH, ACK
)
import host
from touchscreen import TouchScreen, UP, CANCELED, UPDATE, DOWN


class FakeTouchAPI:
    def __init__(self):
        self.frames = []
    def InitializeTouchInjection(self, count, visual):
        return True
    def InjectTouchInput(self, count, frame):
        self.frames.append([(i.pointerInfo.pointerId, i.pointerInfo.pointerFlags,
                             i.pointerInfo.ptPixelLocation.x, i.pointerInfo.ptPixelLocation.y) for i in frame])
        return True


class DualRotationAndOrientationTests(unittest.TestCase):
    def test_display_orientation_validation(self):
        # Valid orientations (iOS UIInterfaceOrientation: 1=Portrait, 2=UpsideDown, 3=LandscapeRight, 4=LandscapeLeft)
        for valid in (1, 2, 3, 4):
            self.assertEqual(display_orientation({'orientation': valid}), valid)
        # Optional field when absent
        self.assertIsNone(display_orientation({}))
        self.assertIsNone(display_orientation({'width': 1024, 'height': 768}))
        self.assertIsNone(display_orientation("not-a-dict"))
        # Invalid values
        for invalid in (0, 5, -1, 3.5, "3", True, False, []):
            with self.assertRaises(ValueError):
                display_orientation({'orientation': invalid})

    def test_dual_landscape_rotation_updates_generation_and_neutralizes_touch(self):
        # When rotating between LandscapeLeft and LandscapeRight (both 1024x768),
        # the session must detect the change, increment generation, and cancel any held touches.
        server, client = socket.socketpair()
        server.settimeout(3)
        client.settimeout(3)
        touch = Mock()
        session = host.Session(server, touch, 30, 1024, False, lambda _: None, 'touch',
                               client_size=(1024, 768), client_display_id=1, client_orientation=3)
        initial_gen = session.display_generation

        # iPad sends new client info: same resolution (1024x768), but opposite orientation (4 = LandscapeLeft)
        new_info = json.dumps({'width': 1024, 'height': 768, 'orientation': 4, 'displayId': 2}).encode()
        session.display_preferences(new_info)

        self.assertEqual(session.client_size, (1024, 768))
        self.assertEqual(session.client_orientation, 4)
        self.assertEqual(session.client_display_id, 2)
        self.assertGreater(session.display_generation, initial_gen)
        # Verify neutral() was called to prevent stuck fingers during rotation
        touch.neutral.assert_called()

        # Verify session.info() reports the orientation
        info = session.info()
        self.assertEqual(info['orientation'], 4)
        self.assertEqual(info['displayId'], 2)

        session.close()
        client.close()

    def test_touch_neutral_resilience_cancels_remaining_contacts_even_if_inject_fails(self):
        api = FakeTouchAPI()
        touch = TouchScreen(api)
        touch.set_monitor({'left': 0, 'top': 0, 'width': 1024, 'height': 768})
        # Add 2 active touches
        touch.events([{'id': 0, 'a': 'down', 'x': 0.2, 'y': 0.2},
                      {'id': 1, 'a': 'down', 'x': 0.8, 'y': 0.8}])
        self.assertEqual(len(touch.contacts), 2)

        # Flaky inject: fail once on the first cancel attempt, ensure the second contact still cancels and contacts dictionary is cleared
        calls = []
        real_inject = api.InjectTouchInput
        def flaky_inject(count, frame):
            calls.append(count)
            if len(calls) == 2:  # fail on second call
                raise OSError("Temporary Windows injection glitch")
            return real_inject(count, frame)

        api.InjectTouchInput = flaky_inject
        touch.neutral()
        self.assertEqual(len(touch.contacts), 0)
        self.assertEqual(len(calls),3)
        self.assertEqual(api.frames[-1][0][0],2)
        self.assertTrue(api.frames[-1][0][1] & UP)
        self.assertTrue(api.frames[-1][0][1] & CANCELED)

    def test_udp_discovery_responder_replies_to_discover_probe(self):
        from discovery import BroadcastResponder
        advertiser = BroadcastResponder('1'*32, 8123, lambda _: None, bind_port=0)

        client_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        client_sock.settimeout(2.0)
        try:
            client_sock.sendto(b'SHOCK_DISCOVER_V1', ('127.0.0.1', advertiser.address[1]))
            reply, _ = client_sock.recvfrom(1024)
            self.assertTrue(reply.startswith(b'SHOCK_REPLY_V1:'))
            payload = json.loads(reply[len(b'SHOCK_REPLY_V1:'):].decode())
            self.assertEqual(payload['hostId'], '1'*32)
            self.assertEqual(payload['port'], 8123)
            self.assertIn('name', payload)
            self.assertIn('addresses', payload)
        finally:
            client_sock.close()
            advertiser.close()
        self.assertFalse(advertiser.thread.is_alive())

    def test_udp_discovery_rejects_prefixes_and_can_restart_after_close(self):
        from discovery import BroadcastResponder
        responder=BroadcastResponder('2'*32,8090,lambda _:None,bind_port=0)
        port=responder.address[1]
        try:
            with socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as client:
                client.settimeout(.15)
                for malformed in (b'SHOCK_DISCOVER',b'SHOCK_DISCOVER_V1extra'):
                    client.sendto(malformed,('127.0.0.1',port))
                    with self.assertRaises(socket.timeout):client.recvfrom(1024)
        finally:responder.close()
        restarted=BroadcastResponder('2'*32,8090,lambda _:None,bind_port=port)
        restarted.close()
        self.assertFalse(restarted.thread.is_alive())


if __name__ == '__main__':
    unittest.main()
