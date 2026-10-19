"""Private TLS rendezvous relay. The forwarded payload remains end-to-end TLS ciphertext."""
import argparse
import asyncio
from dataclasses import dataclass, field
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import sys
import time

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'windows'))
from remote import RemoteIdentity, endpoint

HEX32=re.compile(r'[0-9a-f]{32}\Z');HEX64=re.compile(r'[0-9a-f]{64}\Z')

@dataclass
class Waiting:
    ticket: str
    joined: asyncio.Event = field(default_factory=asyncio.Event)
    done: asyncio.Event = field(default_factory=asyncio.Event)
    client: object = None


class Relay:
    def __init__(self, owner_token, max_routes=8, max_connections=32, heartbeat=15, heartbeat_timeout=5):
        if not isinstance(owner_token,str) or not HEX64.fullmatch(owner_token):raise ValueError('Invalid owner token')
        self.owner_token=owner_token;self.routes={};self.max_routes=max_routes
        self.max_connections=max_connections;self.active=0;self.failures={};self.transferred=0
        self.heartbeat=heartbeat;self.heartbeat_timeout=heartbeat_timeout

    async def reply(self, writer, value):
        writer.write(value+b'\n');await writer.drain()

    async def handle(self, reader, writer):
        peer=writer.get_extra_info('peername');peer=str(peer[0]) if peer else 'unknown'
        now=time.monotonic()
        self.failures={ip:v for ip,v in self.failures.items() if now-v[1]<60}
        # Bounded per-IP failure accounting; do not expose credentials or addresses in logs.
        if self.active>=self.max_connections or self.failures.get(peer,(0,0))[0]>=12:
            writer.close();return
        self.active+=1
        try:
            line=await asyncio.wait_for(reader.readline(),5)
            if not line.endswith(b'\n') or len(line)>1024:raise ValueError('Invalid request')
            value=json.loads(line)
            if not isinstance(value,dict) or type(value.get('v')) is not int or value['v']!=1:raise ValueError('Invalid request')
            route=value.get('route');ticket=value.get('ticket')
            if not isinstance(route,str) or not HEX32.fullmatch(route) or not isinstance(ticket,str) or not HEX64.fullmatch(ticket):
                raise ValueError('Invalid request')
            if value.get('op')=='host':
                token=value.get('owner')
                if not isinstance(token,str) or not hmac.compare_digest(token,self.owner_token):raise PermissionError()
                if route in self.routes or len(self.routes)>=self.max_routes:
                    await self.reply(writer,b'BUSY');return
                waiting=Waiting(ticket);self.routes[route]=waiting
                try:
                    await self.reply(writer,b'WAIT')
                    join_task=asyncio.create_task(waiting.joined.wait())
                    eof_task=asyncio.create_task(reader.read(1))
                    try:
                        while not join_task.done():
                            done,_=await asyncio.wait((join_task,eof_task),timeout=self.heartbeat,return_when=asyncio.FIRST_COMPLETED)
                            if eof_task in done:return # A waiting host sends no application data.
                            if not done:
                                eof_task.cancel();await asyncio.gather(eof_task,return_exceptions=True)
                                await self.reply(writer,b'ALIVE')
                                # Drain the control reply before READY, so it cannot enter inner TLS.
                                if await asyncio.wait_for(reader.readexactly(1),self.heartbeat_timeout)!=b'P':return
                                eof_task=asyncio.create_task(reader.read(1))
                        eof_task.cancel();await asyncio.gather(eof_task,return_exceptions=True)
                        client_reader,client_writer=waiting.client
                        await self.reply(writer,b'READY');await self.reply(client_writer,b'READY')
                        async def pump(source,target):
                            while True:
                                data=await asyncio.wait_for(source.read(16384),45)
                                if not data:return
                                self.transferred+=len(data);target.write(data)
                                await asyncio.wait_for(target.drain(),15)
                        tasks=[asyncio.create_task(pump(reader,client_writer)),asyncio.create_task(pump(client_reader,writer))]
                        try:
                            await asyncio.wait(tasks,timeout=6*3600,return_when=asyncio.FIRST_COMPLETED)
                        finally:
                            for task in tasks:task.cancel()
                            await asyncio.gather(*tasks,return_exceptions=True)
                            client_writer.close()
                    finally:
                        join_task.cancel();eof_task.cancel()
                        await asyncio.gather(join_task,eof_task,return_exceptions=True)
                finally:
                    if self.routes.get(route) is waiting:self.routes.pop(route,None)
                    waiting.done.set()
            elif value.get('op')=='join':
                waiting=self.routes.get(route)
                # Uniform refusal avoids disclosing whether a guessed route exists.
                if not waiting or not hmac.compare_digest(waiting.ticket,ticket) or waiting.joined.is_set():
                    raise PermissionError()
                waiting.client=(reader,writer);waiting.joined.set()
                await waiting.done.wait()
            else:raise ValueError('Invalid request')
        except (ValueError,PermissionError,asyncio.TimeoutError,asyncio.LimitOverrunError):
            count,_=self.failures.get(peer,(0,0))
            if len(self.failures)<1024 or peer in self.failures:self.failures[peer]=(count+1,time.monotonic())
            try:await self.reply(writer,b'DENIED')
            except (ConnectionError,OSError):pass
        except (ConnectionError,OSError):pass
        finally:
            self.active-=1;writer.close()
            try:await asyncio.wait_for(writer.wait_closed(),2)
            except (ConnectionError,OSError,asyncio.TimeoutError):pass


def configuration(directory):
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
    path=directory/'owner.json'
    if not path.exists():
        with path.open('x',encoding='utf-8') as file:json.dump({'token':secrets.token_hex(32)},file)
        path.chmod(0o600)
    value=json.loads(path.read_text(encoding='utf-8'))
    return RemoteIdentity(directory),value['token']


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--data',default='/data')
    parser.add_argument('--listen',default='0.0.0.0');parser.add_argument('--port',type=int,default=8443)
    parser.add_argument('--setup',metavar='PUBLIC_HOST:PORT',help='Write private PC configuration invitation to a file')
    args=parser.parse_args();identity,token=configuration(args.data)
    Relay(token) # Validate config before running or exporting.
    if args.setup:
        host,port=endpoint(args.setup)
        if ':' in host:host='['+host+']'
        path=Path(args.data)/'configurar-pc.txt'
        path.write_text(f'shockrelay://{host}:{port}?cert={identity.fingerprint}&owner={token}\n',encoding='utf-8')
        path.chmod(0o600);print('Private PC setup written to configurar-pc.txt; do not distribute it to clients.');return
    async def run():
        relay=Relay(token)
        server=await asyncio.start_server(relay.handle,args.listen,args.port,ssl=identity.context,
                                          ssl_handshake_timeout=5,limit=2048)
        print('Shock relay ready. Authentication required; forwarded sessions use end-to-end TLS.',flush=True)
        async with server:await server.serve_forever()
    asyncio.run(run())

if __name__=='__main__':main()
