"""Opt-in, certificate-pinned TLS transport. No router or firewall changes."""
import datetime
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import secrets
import ssl
from urllib.parse import urlsplit, parse_qs

PORT = 8093
HEX64 = re.compile(r'[0-9a-f]{64}\Z')


def endpoint(value):
    """Only a host and optional port, never a URL with credentials or a path."""
    if not isinstance(value, str) or not value or any(c.isspace() for c in value):
        raise ValueError('Informe IP público ou nome DNS, com porta opcional (ex.: casa.example:8093).')
    parsed = urlsplit('//'+value)
    try:
        host, port = parsed.hostname, parsed.port if parsed.port is not None else PORT
    except ValueError as exc:
        raise ValueError('Endereço remoto inválido') from exc
    if not host or parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment:
        raise ValueError('Use apenas endereço:porta, sem senha, caminho ou http://')
    try:
        ipaddress.ip_address(host)
    except ValueError:
        if len(host)>253 or any(not re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?', p) for p in host.split('.')):
            raise ValueError('Nome DNS inválido')
    if not 1 <= port <= 65535:
        raise ValueError('Porta inválida')
    return host, port


class RemoteIdentity:
    def __init__(self, directory=None):
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.x509.oid import NameOID
        self.directory = Path(directory) if directory else Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'ShockStream' / 'remote'
        self.directory.mkdir(parents=True, exist_ok=True)
        pem = self.directory / 'identity.pem'
        if not pem.exists():
            key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
            name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'Shock Stream remote')])
            now = datetime.datetime.now(datetime.timezone.utc)
            cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
                    .serial_number(x509.random_serial_number()).not_valid_before(now-datetime.timedelta(days=1))
                    .not_valid_after(now+datetime.timedelta(days=3650))
                    .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
                    .sign(key, hashes.SHA256()))
            data = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                     serialization.NoEncryption()) + cert.public_bytes(serialization.Encoding.PEM)
            # Exclusive create: never replace the identity of an already paired PC.
            with pem.open('xb') as file:
                file.write(data)
            pem.chmod(0o600)
        cert = x509.load_pem_x509_certificate(pem.read_bytes())
        self.fingerprint = cert.fingerprint(hashes.SHA256()).hex()
        secret = self.directory / 'access.json'
        if secret.exists():
            self.key = json.loads(secret.read_text(encoding='utf-8'))['key']
            if not isinstance(self.key, str) or not HEX64.fullmatch(self.key):
                raise ValueError('Chave remota inválida; restaure o arquivo access.json')
        else:
            self.key = secrets.token_hex(32)
            self._save_key(secret)
        self.context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        self.context.minimum_version = ssl.TLSVersion.TLSv1_2
        self.context.set_ciphers('ECDHE-RSA-AES128-GCM-SHA256:ECDHE-RSA-AES256-GCM-SHA384')
        self.context.load_cert_chain(str(pem))

    def _save_key(self, path):
        temporary = path.with_suffix('.tmp')
        temporary.write_text(json.dumps({'key':self.key}), encoding='utf-8')
        temporary.chmod(0o600)
        temporary.replace(path)

    def revoke(self):
        self.key = secrets.token_hex(32)
        self._save_key(self.directory / 'access.json')

    def invitation(self, address):
        host, port = endpoint(address)
        if ':' in host:host='['+host+']'
        return f'shockstream://{host}:{port}?key={self.key}&cert={self.fingerprint}'


def parse_invitation(value):
    parsed = urlsplit(value)
    if parsed.scheme != 'shockstream' or parsed.path or parsed.fragment:
        raise ValueError('Convite inválido')
    host, port = endpoint(parsed.netloc)
    query = parse_qs(parsed.query, strict_parsing=True)
    if set(query) != {'key','cert'} or any(len(v)!=1 or not HEX64.fullmatch(v[0]) for v in query.values()):
        raise ValueError('Convite inválido')
    return host, port, query['key'][0], query['cert'][0]


def pinned_client(sock, fingerprint):
    """Integration-test client: identity is the exact invited certificate, not public PKI."""
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    secured = context.wrap_socket(sock)
    if not secrets.compare_digest(hashlib.sha256(secured.getpeercert(binary_form=True)).hexdigest(), fingerprint):
        secured.close()
        raise ssl.SSLCertVerificationError('O certificado não corresponde ao convite')
    return secured
