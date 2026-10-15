"""Shock Stream v1: bounded packets and complete gamepad snapshots."""
import hashlib
import hmac
import math
import socket
import struct
import threading
import time

MAGIC = b"SHOCK1"
VIDEO, AUDIO, INFO, ERROR = 1, 2, 3, 4
ACK, PAD, BYE, HEARTBEAT = 10, 11, 12, 13
TOUCH, CLIENT_INFO = 14, 15
NOTICE = 16
MAX_PACKET = 4 * 1024 * 1024
HEADER = struct.Struct("!BI")


def read_exact(sock, size):
    result = bytearray()
    while len(result) < size:
        chunk = sock.recv(size - len(result))
        if not chunk:
            raise ConnectionError("Conexão encerrada")
        result.extend(chunk)
    return bytes(result)


def packet(kind, body=b""):
    if len(body) > MAX_PACKET:
        raise ValueError("Pacote excede o limite")
    return HEADER.pack(kind, len(body)) + body


def read_packet(sock):
    kind, size = HEADER.unpack(read_exact(sock, HEADER.size))
    if size > MAX_PACKET:
        raise ValueError("Pacote excede o limite")
    return kind, read_exact(sock, size)


def proof(pin, nonce):
    return hmac.new(pin.encode("ascii"), nonce, hashlib.sha256).digest()


def fit_size(width, height, longest=1024):
    scale = min(1.0, longest / max(width, height))
    return max(2, int(width * scale) & ~1), max(2, int(height * scale) & ~1)


def validate_display(value):
    if not isinstance(value, dict):
        raise ValueError('Tela do iPad inválida')
    size = (value.get('width'), value.get('height'))
    if any(isinstance(n, bool) or not isinstance(n, int) for n in size):
        raise ValueError('Resolução inválida')
    if size not in ((1024, 768), (768, 1024)):
        raise ValueError('Resolução fora do display do iPad mini 1')
    return size


def display_id(value):
    identity = value.get('displayId')
    if identity is not None and (isinstance(identity, bool) or not isinstance(identity, int) or not 0 <= identity <= 2147483647):
        raise ValueError('Identificador de tela inválido')
    return identity


def validate_pad(value):
    if not isinstance(value, dict):
        raise ValueError("Estado de controle inválido")
    result = {}
    for name in ("lx", "ly", "rx", "ry", "lt", "rt"):
        number = value.get(name, 0)
        if isinstance(number, bool) or not isinstance(number, (int, float)) or not math.isfinite(number):
            raise ValueError("Eixo inválido")
        low = 0 if name in ("lt", "rt") else -1
        result[name] = max(low, min(1, number))
    buttons = value.get("buttons", 0)
    if isinstance(buttons, bool) or not isinstance(buttons, int) or buttons < 0 or buttons > 65535:
        raise ValueError("Botões inválidos")
    result["buttons"] = buttons & 0xF3FF  # Known XInput buttons only.
    return result


class LatestFrame:
    """Capture overwrites one slot; the sender never drains an old frame queue."""
    def __init__(self):
        self.condition = threading.Condition()
        self.value = None
        self.sequence = 0

    def put(self, value):
        with self.condition:
            self.value = value
            self.sequence += 1
            self.condition.notify_all()

    def take_after(self, sequence, timeout=0.5):
        deadline = time.monotonic() + timeout
        with self.condition:
            while self.sequence <= sequence:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return sequence, None
                self.condition.wait(remaining)
            return self.sequence, self.value
