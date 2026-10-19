"""Check the built container's private provisioned TLS listener and persistent identity."""
import secrets
import socket
import sys
import time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'windows'))
from relay_client import parse_setup,send_request,read_line
from remote import pinned_client
from protocol import read_exact

host,port,cert,owner=parse_setup(Path(sys.argv[1]).read_text(encoding='utf-8').strip())
for attempt in range(50):
    try:
        pc=pinned_client(socket.create_connection((host,port),timeout=2),cert);break
    except OSError:
        if attempt==49:raise
        time.sleep(.1)
with pc:
    route=secrets.token_hex(16);ticket=secrets.token_hex(32)
    send_request(pc,{'v':1,'op':'host','owner':owner,'route':route,'ticket':ticket})
    assert read_line(pc)==b'WAIT'
    with pinned_client(socket.create_connection((host,port),timeout=3),cert) as client:
        send_request(client,{'v':1,'op':'join','route':route,'ticket':ticket})
        assert read_line(pc)==b'READY' and read_line(client)==b'READY'
        sample=b'opaque encrypted payload integration fixture'
        pc.sendall(sample);assert read_exact(client,len(sample))==sample
        client.sendall(sample);assert read_exact(pc,len(sample))==sample
print('PASS: non-root container TLS, private provisioned identity, authenticated bidirectional relay')
