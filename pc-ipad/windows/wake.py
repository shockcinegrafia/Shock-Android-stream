"""Authenticated USB requests to the optional jailbreak helper, separate from video."""
import hashlib
import hmac
import json
import re
import struct
import time

from protocol import read_exact

MAGIC = b'SHOCKW1'
AUTO, RESUME, STATUS = 0, 1, 2
STATUSES = {'launch_requested', 'already_active', 'paused', 'not_paired', 'auth_failed',
            'launch_failed', 'locked', 'unsupported', 'idle'}


class WakeAuthenticationError(ConnectionError):
    pass


def request(sock, host_id, key_hex, operation=AUTO):
    if not isinstance(host_id, str) or not re.fullmatch(r'[0-9a-f]{32}', host_id):
        raise ValueError('Identidade do PC inválida')
    if not isinstance(key_hex, str) or not re.fullmatch(r'[0-9a-f]{64}', key_hex):
        raise ValueError('Chave de abertura automática inválida')
    if isinstance(operation, bool) or operation not in (AUTO, RESUME, STATUS):
        raise ValueError('Operação de abertura inválida')
    key = bytes.fromhex(key_hex)
    sock.settimeout(3)
    challenge = read_exact(sock, len(MAGIC) + 32)
    if challenge[:len(MAGIC)] != MAGIC:
        raise ValueError('Serviço de abertura incompatível')
    nonce = challenge[len(MAGIC):]
    identity = host_id.encode('ascii')
    opcode = bytes([operation])
    mac = hmac.digest(key, b'client\0' + nonce + identity + opcode, 'sha256')
    sock.sendall(struct.pack('!H', len(identity)) + identity + opcode + mac)
    length, = struct.unpack('!I', read_exact(sock, 4))
    if not 2 <= length <= 4096:
        raise ValueError('Resposta de abertura excede o limite')
    body = read_exact(sock, length)
    received_mac = read_exact(sock, 32)
    expected = hmac.digest(key, b'server\0' + nonce + opcode + body, 'sha256')
    if not hmac.compare_digest(received_mac, expected):
        raise WakeAuthenticationError('Abra o app no iPad e emparelhe uma vez; o auxiliar não confirmou a chave deste PC.')
    value = json.loads(body)
    if not isinstance(value, dict) or value.get('status') not in STATUSES:
        raise ValueError('Estado do auxiliar inválido')
    return value


def request_usb(device_id, identity, operation=AUTO):
    from usbmux import connect_device
    with connect_device(device_id, port=8092) as connection:
        return request(connection, identity['hostId'], identity.get('wakeKey'), operation)


class RetryBudget:
    """Bound automatic launches; explicit resume or a new USB device epoch resets it."""
    def __init__(self):
        self.epoch = None
        self.attempts = 0
        self.next_attempt = 0

    def reset(self, epoch):
        if epoch != self.epoch:
            self.epoch = epoch
            self.attempts = 0
            self.next_attempt = 0

    def allow(self, now=None, explicit=False):
        now = time.monotonic() if now is None else now
        if explicit:
            self.attempts = 0
            self.next_attempt = 0
        if self.attempts >= 3 or now < self.next_attempt:
            return False
        self.attempts += 1
        self.next_attempt = now + 10
        return True
