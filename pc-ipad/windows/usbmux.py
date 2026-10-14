"""Apple USB tunnel, including older Windows usbmux service protocols.

Enumeration follows libusbmuxd's ListDevices -> Listen fallback. A daemon
rejecting protocol 1 with BadVersion is retried on a fresh protocol 0 socket.
No pairing records or device identifiers are included in diagnostic messages.
"""
import plistlib
import socket
import struct
import time

HEADER = struct.Struct('<IIII')
DEVICE_RECORD = struct.Struct('<IH256sHI')
SERVICE = ('127.0.0.1', 27015)
MAX_MESSAGE = 1024 * 1024
RESULT, CONNECT, LISTEN, ATTACHED, DETACHED, PAIRED, PLIST = 1, 2, 3, 4, 5, 6, 8
BAD_VERSION = 6
SCAN_QUIET = 0.35
SCAN_LIMIT = 2.0


class USBServiceUnavailable(RuntimeError):
    """The local Apple service cannot be reached, independently of the cable."""


class _Unsupported(Exception):
    def __init__(self, code=None):
        self.code = code


def _open(service, timeout=2):
    try:
        return socket.create_connection(service, timeout=timeout)
    except OSError as error:
        raise USBServiceUnavailable(
            'Serviço USB Apple indisponível. Use Preparar USB Apple; '
            'confira se Apple Mobile Device Service está em execução.'
        ) from error


def _read_exact(sock, size, deadline, idle=False):
    data = bytearray()
    while len(data) < size:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            if idle and not data:
                raise socket.timeout('Tempo de espera USB esgotado')
            raise ValueError('Resposta USB da Apple truncada')
        sock.settimeout(remaining)
        try:
            part = sock.recv(size - len(data))
        except socket.timeout as error:
            if idle and not data:
                raise
            raise ValueError('Resposta USB da Apple truncada') from error
        if not part:
            if not data and idle:
                raise ConnectionError('O serviço USB Apple encerrou a conexão')
            raise ValueError('Resposta USB da Apple truncada')
        data.extend(part)
    return bytes(data)


def _receive(sock, deadline):
    length, version, kind, tag = HEADER.unpack(
        _read_exact(sock, HEADER.size, deadline, idle=True))
    if length < HEADER.size or length > MAX_MESSAGE or version not in (0, 1):
        raise ValueError('Cabeçalho USB da Apple inválido')
    body = _read_exact(sock, length - HEADER.size, deadline)
    if kind == PLIST:
        try:
            message = plistlib.loads(body)
        except Exception as error:
            raise ValueError('Resposta plist USB da Apple inválida') from error
        if not isinstance(message, dict):
            raise ValueError('Resposta plist USB da Apple inválida')
    elif kind == RESULT and len(body) == 4:
        message = {'MessageType': 'Result', 'Number': struct.unpack('<I', body)[0]}
    elif kind == ATTACHED and len(body) == DEVICE_RECORD.size:
        device_id, product, serial, _, location = DEVICE_RECORD.unpack(body)
        message = {'MessageType': 'Attached', 'DeviceID': device_id, 'Properties': {
            'DeviceID': device_id, 'ProductID': product, 'ConnectionType': 'USB',
            'SerialNumber': serial.split(b'\0', 1)[0].decode('ascii', errors='replace'),
            'LocationID': location}}
    elif kind in (DETACHED, PAIRED) and len(body) == 4:
        message = {'MessageType': 'Detached' if kind == DETACHED else 'Paired',
                   'DeviceID': struct.unpack('<I', body)[0]}
    else:
        raise ValueError('Tipo ou tamanho de resposta USB da Apple inválido')
    return tag, message


def _send(sock, message, tag=1, version=1):
    if version == 1:
        body = plistlib.dumps({'ClientVersionString': 'ShockStream',
                              'ProgName': 'ShockStream', 'kLibUSBMuxVersion': 3,
                              **message}, fmt=plistlib.FMT_XML)
        kind = PLIST
    elif message['MessageType'] == 'Listen':
        kind, body = LISTEN, b''
    elif message['MessageType'] == 'Connect':
        kind = CONNECT
        body = struct.pack('<IHH', message['DeviceID'], message['PortNumber'], 0)
    else:
        raise ValueError('Comando USB binário inválido')
    sock.sendall(HEADER.pack(HEADER.size + len(body), version, kind, tag) + body)


def exchange(sock, message, tag=1, version=1):
    """Send a request; binary Result replies are also valid for plist requests."""
    _send(sock, message, tag, version)
    response_tag, reply = _receive(sock, time.monotonic() + SCAN_LIMIT)
    if response_tag != tag:
        raise ValueError('Identificador de resposta USB da Apple inválido')
    return reply


def _result(reply):
    number = reply.get('Number')
    if reply.get('MessageType') != 'Result' or isinstance(number, bool) or not isinstance(number, int):
        raise ValueError('Resultado USB da Apple inválido')
    return number


def _devices(values):
    if not isinstance(values, list):
        raise ValueError('Lista USB da Apple inválida')
    devices = {}
    for device in values:
        if not isinstance(device, dict) or not isinstance(device.get('Properties'), dict):
            raise ValueError('Dispositivo USB da Apple inválido')
        properties = device['Properties']
        if properties.get('ConnectionType', 'USB') != 'USB':
            continue
        device_id = device.get('DeviceID', properties.get('DeviceID'))
        if isinstance(device_id, bool) or not isinstance(device_id, int) or not 0 < device_id <= 0xffffffff:
            raise ValueError('Identificador de dispositivo USB da Apple inválido')
        devices[device_id] = {**device, 'DeviceID': device_id,
                              'Properties': {**properties, 'ConnectionType': 'USB'}}
    return list(devices.values())


def _listen_devices(service, version):
    with _open(service) as sock:
        _send(sock, {'MessageType': 'Listen'}, version=version)
        limit = time.monotonic() + SCAN_LIMIT
        deadline, acknowledged, devices = limit, False, {}
        while True:
            try:
                tag, reply = _receive(sock, deadline)
            except (socket.timeout, ConnectionError):
                if not acknowledged:
                    raise RuntimeError('O serviço USB Apple não confirmou a detecção do iPad')
                return list(devices.values())
            kind = reply.get('MessageType')
            if kind == 'Result':
                if tag != 1 or acknowledged:
                    raise ValueError('Identificador de resposta USB da Apple inválido')
                code = _result(reply)
                if code:
                    raise _Unsupported(code)
                acknowledged = True
            elif kind == 'Attached':
                for device in _devices([reply]):
                    devices[device['DeviceID']] = device
            elif kind in ('Detached', 'Paired'):
                device_id = reply.get('DeviceID')
                if isinstance(device_id, bool) or not isinstance(device_id, int) or not 0 < device_id <= 0xffffffff:
                    raise ValueError('Identificador de evento USB da Apple inválido')
                if kind == 'Detached':
                    devices.pop(device_id, None)
            else:
                raise ValueError('Evento USB da Apple inválido')
            if acknowledged:
                deadline = min(limit, time.monotonic() + SCAN_QUIET)
                if deadline <= time.monotonic():
                    return list(devices.values())


def list_devices(service=SERVICE):
    """Return USB devices, never mistaking an unsupported command for an empty list."""
    with _open(service) as sock:
        reply = exchange(sock, {'MessageType': 'ListDevices'})
    if 'DeviceList' in reply:
        return _devices(reply['DeviceList'])
    # Some Apple daemons implement Listen but not the newer ListDevices command.
    version = 0 if reply.get('Number') == BAD_VERSION else 1
    try:
        return _listen_devices(service, version)
    except _Unsupported as error:
        if version == 1 and error.code == BAD_VERSION:
            try:
                return _listen_devices(service, 0)
            except _Unsupported as binary_error:
                raise RuntimeError('O serviço USB Apple recusou a detecção. Código '
                                   + str(binary_error.code)) from binary_error
        raise RuntimeError('O serviço USB Apple recusou a detecção. Código '
                           + str(error.code)) from error


def connect_device(device_id, port=8091, service=SERVICE, serial_number=None):
    """Open a tunnel; optional stable serial survives DeviceID changes on reconnect."""
    if serial_number is not None:
        matches = [d for d in list_devices(service)
                   if d['Properties'].get('SerialNumber') == serial_number]
        if len(matches) != 1:
            raise ConnectionError('O iPad selecionado não está conectado pelo USB. Detecte novamente.')
        device_id = matches[0]['DeviceID']
    if isinstance(device_id, bool) or not isinstance(device_id, int) or not 0 < device_id <= 0xffffffff:
        raise ValueError('Identificador USB inválido')
    if isinstance(port, bool) or not isinstance(port, int) or not 0 < port <= 65535:
        raise ValueError('Porta USB inválida')
    message = {'MessageType': 'Connect', 'DeviceID': device_id, 'PortNumber': socket.htons(port)}
    for version in (1, 0):
        sock = _open(service, timeout=3)
        try:
            code = _result(exchange(sock, message, version=version))
            if code == BAD_VERSION and version == 1:
                sock.close()
                continue
            if code == 2:
                raise ConnectionError('O iPad foi desconectado ou mudou de identificador. Detecte novamente.')
            if code == 3:
                raise ConnectionError('iPad detectado, mas o app não está aguardando. '
                                      'Abra o app Shock Stream no iPad e aguarde o PC. '
                                      'Em versões antigas, toque Aguardar PC. Resposta USB: 3')
            if code:
                raise ConnectionError('O serviço USB Apple recusou a conexão. Resposta USB: ' + str(code))
            sock.settimeout(5)
            return sock  # The same socket now carries the application data, unframed by usbmux.
        except Exception:
            sock.close()
            raise


def diagnostics(service=SERVICE):
    """A bounded readiness probe, containing no device serials or pairing secrets."""
    try:
        devices = list_devices(service)
    except USBServiceUnavailable as error:
        return {'status': 'service_unavailable', 'device_count': 0, 'message': str(error)}
    except (RuntimeError, OSError, ValueError) as error:
        return {'status': 'protocol_error', 'device_count': 0, 'message': str(error)}
    if not devices:
        return {'status': 'no_device', 'device_count': 0,
                'message': 'Serviço Apple ativo; nenhum iPad USB detectado. '
                           'Use um cabo de dados, desbloqueie o iPad e confirme Confiar.'}
    return {'status': 'ready', 'device_count': len(devices),
            'message': 'iPad USB detectado. Abra o app Shock Stream no iPad e aguarde o PC.'}
