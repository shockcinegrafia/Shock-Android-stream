"""Exercise Apple daemon variants over real TCP sockets, without Apple drivers."""
import json
from pathlib import Path
import plistlib
import socket
import struct
import sys
import threading
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'windows'))
import usbmux
from protocol import read_exact


def wire(message, tag=1, version=1):
    body = plistlib.dumps(message)
    return usbmux.HEADER.pack(16 + len(body), version, usbmux.PLIST, tag) + body


def binary(kind, body=b'', tag=1):
    return usbmux.HEADER.pack(16 + len(body), 0, kind, tag) + body


def result(code=0, tag=1):
    return binary(usbmux.RESULT, struct.pack('<I', code), tag)


def device(ident=7, serial='test-ipad', connection='USB'):
    return {'DeviceID': ident, 'Properties': {
        'DeviceID': ident, 'SerialNumber': serial, 'ConnectionType': connection}}


class Daemon:
    """Run one expected request per connection; surface worker errors in the test."""
    def __init__(self, *handlers):
        self.handlers, self.requests, self.errors = handlers, [], []

    def __enter__(self):
        self.listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.listener.bind(('127.0.0.1', 0))
        self.listener.listen(4)
        self.listener.settimeout(2)
        self.address = self.listener.getsockname()
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()
        return self

    def run(self):
        try:
            for handler in self.handlers:
                connection, _ = self.listener.accept()
                with connection:
                    connection.settimeout(2)
                    size, version, kind, tag = usbmux.HEADER.unpack(read_exact(connection, 16))
                    body = read_exact(connection, size - 16)
                    request = plistlib.loads(body) if kind == usbmux.PLIST else body
                    self.requests.append((version, kind, tag, request))
                    handler(connection, request)
        except Exception as error:
            self.errors.append(error)

    def __exit__(self, exc_type, exc_value, traceback):
        self.thread.join(3)
        self.listener.close()
        if not exc_type:
            if self.thread.is_alive():
                raise AssertionError('Simulated Apple daemon did not finish')
            if self.errors:
                raise AssertionError(self.errors)


def send(payload):
    return lambda connection, _: connection.sendall(payload)


class USBMuxCompatibilityTests(unittest.TestCase):
    def test_list_devices_plist_includes_apple_client_version_and_filters_network(self):
        values = [device(1, connection='Network'), device(7)]
        with Daemon(send(wire({'DeviceList': values}))) as daemon:
            found = usbmux.list_devices(daemon.address)
        self.assertEqual([d['DeviceID'] for d in found], [7])
        self.assertEqual(daemon.requests[0][3]['kLibUSBMuxVersion'], 3)

    def test_listdevices_unsupported_falls_back_to_plist_listen(self):
        event = {'MessageType': 'Attached', **device()}
        with Daemon(send(wire({'MessageType': 'Result', 'Number': 1})),
                    send(wire({'MessageType': 'Result', 'Number': 0}) + wire(event, tag=0))) as daemon:
            found = usbmux.list_devices(daemon.address)
        self.assertEqual(found[0]['Properties']['SerialNumber'], 'test-ipad')
        self.assertEqual([request[3]['MessageType'] for request in daemon.requests],
                         ['ListDevices', 'Listen'])

    def test_success_without_list_is_not_treated_as_no_device(self):
        with Daemon(send(wire({'MessageType': 'Result', 'Number': 0})),
                    send(result() + wire({'MessageType': 'Attached', **device()}, tag=0))) as daemon:
            self.assertEqual(usbmux.list_devices(daemon.address)[0]['DeviceID'], 7)

    def test_bad_version_on_listdevices_uses_binary_listen(self):
        record = usbmux.DEVICE_RECORD.pack(42, 0x12ab, b'legacy-ipad', 0, 0x1234)
        with Daemon(send(result(6)), send(result() + binary(usbmux.ATTACHED, record, tag=0))) as daemon:
            found = usbmux.list_devices(daemon.address)
        self.assertEqual(daemon.requests[1][:2], (0, usbmux.LISTEN))
        self.assertEqual(daemon.requests[1][3], b'')
        self.assertEqual(found[0]['DeviceID'], 42)
        self.assertEqual(found[0]['Properties']['SerialNumber'], 'legacy-ipad')

    def test_bad_version_on_plist_listen_retries_binary_on_new_socket(self):
        record = usbmux.DEVICE_RECORD.pack(9, 123, b'ipad', 0, 1)
        with Daemon(send(wire({'MessageType': 'Result', 'Number': 1})), send(result(6)),
                    send(result() + binary(usbmux.ATTACHED, record, tag=0))) as daemon:
            self.assertEqual(usbmux.list_devices(daemon.address)[0]['DeviceID'], 9)
        self.assertEqual([r[0] for r in daemon.requests], [1, 1, 0])

    def test_listen_tracks_detach_duplicate_and_network_events(self):
        events = [wire({'MessageType': 'Attached', **device(7)}, tag=0),
                  wire({'MessageType': 'Attached', **device(7)}, tag=0),
                  wire({'MessageType': 'Attached', **device(9, connection='Network')}, tag=0),
                  wire({'MessageType': 'Detached', 'DeviceID': 7}, tag=0),
                  wire({'MessageType': 'Attached', **device(10)}, tag=0),
                  wire({'MessageType': 'Paired', 'DeviceID': 10}, tag=0)]
        with Daemon(send(result(1)), send(result() + b''.join(events))) as daemon:
            self.assertEqual([d['DeviceID'] for d in usbmux.list_devices(daemon.address)], [10])

    def test_binary_detach_is_honored(self):
        record = usbmux.DEVICE_RECORD.pack(9, 123, b'ipad', 0, 1)
        payload = result() + binary(usbmux.ATTACHED, record, tag=0)
        payload += binary(usbmux.DETACHED, struct.pack('<I', 9), tag=0)
        with Daemon(send(result(6)), send(payload)) as daemon:
            self.assertEqual(usbmux.list_devices(daemon.address), [])

    def test_listen_collection_ends_when_daemon_stays_open(self):
        def listen(connection, _):
            connection.sendall(result())
            self.assertEqual(connection.recv(1), b'')
        with Daemon(send(result(1)), listen) as daemon, patch.object(usbmux, 'SCAN_QUIET', 0.03):
            self.assertEqual(usbmux.list_devices(daemon.address), [])

    def test_connect_binary_fallback_preserves_tunnel_data(self):
        def tunnel(connection, request):
            self.assertEqual(struct.unpack('<IHH', request), (7, socket.htons(8091), 0))
            connection.sendall(result() + b'HELLO')
            connection.sendall(read_exact(connection, 4))
        with Daemon(send(result(6)), tunnel) as daemon:
            with usbmux.connect_device(7, service=daemon.address) as connection:
                self.assertEqual(read_exact(connection, 5), b'HELLO')
                connection.sendall(b'PING')
                self.assertEqual(read_exact(connection, 4), b'PING')
        self.assertEqual(daemon.requests[1][:2], (0, usbmux.CONNECT))

    def test_plist_connect_accepts_binary_success_without_switching(self):
        with Daemon(send(result())) as daemon:
            usbmux.connect_device(7, service=daemon.address).close()
        self.assertEqual(daemon.requests[0][0], 1)
        self.assertEqual(daemon.requests[0][3]['PortNumber'], socket.htons(8091))

    def test_closed_app_port_is_distinct_from_missing_service(self):
        with Daemon(send(result(3))) as daemon:
            with self.assertRaisesRegex(ConnectionError, 'Aguardar PC'):
                usbmux.connect_device(7, service=daemon.address)

    def test_detached_device_is_reported_without_retrying_the_app_port(self):
        with Daemon(send(result(2))) as daemon:
            with self.assertRaisesRegex(ConnectionError, 'Detecte novamente'):
                usbmux.connect_device(7, service=daemon.address)

    def test_stable_serial_resolves_new_device_id(self):
        with Daemon(send(wire({'DeviceList': [device(77, 'same-ipad')]})), send(result())) as daemon:
            usbmux.connect_device(7, service=daemon.address, serial_number='same-ipad').close()
        self.assertEqual(daemon.requests[1][3]['DeviceID'], 77)

    def test_missing_stable_serial_does_not_connect_to_another_device(self):
        with Daemon(send(wire({'DeviceList': [device(77, 'other-ipad')]}))) as daemon:
            with self.assertRaisesRegex(ConnectionError, 'não está conectado'):
                usbmux.connect_device(7, service=daemon.address, serial_number='same-ipad')

    def test_fragmented_header_and_payload_are_reassembled(self):
        payload = wire({'DeviceList': [device()]})
        def fragmented(connection, _):
            for offset in range(0, len(payload), 11):
                connection.sendall(payload[offset:offset + 11])
                time.sleep(0.001)
        with Daemon(fragmented) as daemon:
            self.assertEqual(usbmux.list_devices(daemon.address)[0]['DeviceID'], 7)

    def test_malformed_packet_is_rejected(self):
        for payload in (usbmux.HEADER.pack(15, 1, 8, 1),
                        usbmux.HEADER.pack(usbmux.MAX_MESSAGE + 1, 1, 8, 1),
                        wire({'DeviceList': []}, version=99),
                        wire({'DeviceList': []}, tag=99),
                        usbmux.HEADER.pack(20, 1, 8, 1) + b'junk',
                        wire({'DeviceList': True})):
            with self.subTest(payload=payload[:16]), Daemon(send(payload)) as daemon:
                with self.assertRaises(ValueError):
                    usbmux.list_devices(daemon.address)

    def test_partial_payload_cannot_be_misreported_as_empty_device_list(self):
        payload = usbmux.HEADER.pack(100, 1, 8, 1) + b'partial'
        with Daemon(send(payload)) as daemon:
            with self.assertRaisesRegex(ValueError, 'truncada'):
                usbmux.list_devices(daemon.address)

    def test_diagnostics_distinguish_no_device_ready_and_service_missing(self):
        for values, status in (([], 'no_device'), ([device()], 'ready')):
            with self.subTest(status=status), Daemon(send(wire({'DeviceList': values}))) as daemon:
                diagnostic = usbmux.diagnostics(daemon.address)
            self.assertEqual(diagnostic['status'], status)
            self.assertNotIn('test-ipad', json.dumps(diagnostic))
        with patch.object(usbmux.socket, 'create_connection', side_effect=ConnectionRefusedError):
            self.assertEqual(usbmux.diagnostics()['status'], 'service_unavailable')

    def test_protocol_failure_has_distinct_diagnostic(self):
        with Daemon(send(wire({'DeviceList': False}))) as daemon:
            self.assertEqual(usbmux.diagnostics(daemon.address)['status'], 'protocol_error')

    def test_invalid_connection_parameters_are_rejected_before_opening_service(self):
        with patch.object(usbmux.socket, 'create_connection') as connect:
            for ident, port in ((0, 8091), (True, 8091), (7, 0), (7, 65536)):
                with self.subTest(ident=ident, port=port), self.assertRaises(ValueError):
                    usbmux.connect_device(ident, port)
            connect.assert_not_called()


if __name__ == '__main__':
    unittest.main()
