"""Bonjour service compatible with NSNetServiceBrowser on iOS 9."""
import socket
import threading
import json
import logging

SERVICE_TYPE = '_shockstream._tcp.local.'
DISCOVERY_PORT = 8090
DISCOVER = b'SHOCK_DISCOVER_V1'
REPLY = b'SHOCK_REPLY_V1:'


def local_ipv4():
    try:
        values = {item[4][0] for item in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)}
    except OSError:
        values = set()
    return sorted(ip for ip in values if not ip.startswith(('127.', '0.')))


def service_info(host_id, port, addresses):
    from zeroconf import ServiceInfo
    # Credentials deliberately stay out of TXT records and multicast packets.
    return ServiceInfo(SERVICE_TYPE, f'ShockStream-{host_id[:12]}.{SERVICE_TYPE}',
                       addresses=[socket.inet_aton(ip) for ip in addresses], port=port,
                       properties={'hostId': host_id, 'name': socket.gethostname(), 'version': '3'},
                       server=f'shock-{host_id}.local.')


class BroadcastResponder:
    """Independent UDP fallback; never advertises the PIN or wake key."""
    def __init__(self, host_id, port, report, bind_port=DISCOVERY_PORT):
        self.stop_event = threading.Event()
        self.thread = None
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            if hasattr(socket, 'SO_EXCLUSIVEADDRUSE'):
                self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            self.sock.bind(('0.0.0.0', bind_port))
            self.sock.settimeout(0.2)
        except OSError:
            self.sock.close()
            raise
        self.address = self.sock.getsockname()
        self.host_id, self.port = host_id, port
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()

    def run(self):
        while not self.stop_event.is_set():
            try:
                data, address = self.sock.recvfrom(512)
                if data != DISCOVER:
                    continue
                payload = json.dumps({'hostId': self.host_id, 'name': socket.gethostname()[:128],
                                      'port': self.port, 'addresses': local_ipv4()[:16]}).encode('utf-8')
                reply = REPLY + payload
                if len(reply) <= 1024:
                    self.sock.sendto(reply, address)
            except socket.timeout:
                continue
            except OSError:
                break

    def close(self):
        self.stop_event.set()
        self.sock.close()
        if self.thread is not threading.current_thread():
            self.thread.join(timeout=1)


class Advertiser:
    def __init__(self, host_id, port, report):
        self.host_id, self.port, self.report = host_id, port, report
        self.stop_event = threading.Event()
        self.broadcast = None
        try:
            self.broadcast = BroadcastResponder(host_id, port, report)
        except OSError as exc:
            logging.warning('UDP discovery unavailable: %s', exc)
            self.report('Busca Wi-Fi por broadcast indisponível; Bonjour e IP manual continuam disponíveis.')
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()

    def run(self):
        from zeroconf import Zeroconf, IPVersion, InterfaceChoice
        zeroconf = None
        info = None
        try:
            zeroconf = Zeroconf(ip_version=IPVersion.V4Only)
            previous = []
            while not self.stop_event.is_set():
                addresses = local_ipv4()
                if addresses != previous:
                    zeroconf.update_interfaces(interfaces=InterfaceChoice.All, ip_version=IPVersion.V4Only)
                    next_info = service_info(self.host_id, self.port, addresses)
                    if info:
                        if addresses:
                            zeroconf.update_service(next_info)
                        else:
                            zeroconf.unregister_service(info)
                    elif addresses:
                        zeroconf.register_service(next_info)
                    info = next_info if addresses else None
                    previous = addresses
                self.stop_event.wait(5)
        except Exception as exc:
            self.report('Descoberta Wi-Fi indisponível; conexão manual por IP continua disponível: ' + str(exc))
        finally:
            if zeroconf:
                try:
                    if info:
                        zeroconf.unregister_service(info)
                finally:
                    zeroconf.close()

    def close(self):
        self.stop_event.set()
        if self.broadcast:
            self.broadcast.close()
        if self.thread is not threading.current_thread():
            self.thread.join(timeout=3)
