"""Real local relay fixture; no public hosting, device input, or system changes."""
import asyncio
import importlib.util
import sys
import threading
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'windows'))
spec=importlib.util.spec_from_file_location('shock_relay_server',Path(__file__).resolve().parents[1]/'relay/server.py')
module=importlib.util.module_from_spec(spec);sys.modules[spec.name]=module;spec.loader.exec_module(module)
Relay=module.Relay

class RelayServer:
    def __init__(self,identity,owner):
        self.identity=identity;self.relay=Relay(owner);self.ready=threading.Event()
        self.thread=threading.Thread(target=self.run,daemon=True);self.thread.start()
        if not self.ready.wait(5):raise RuntimeError('Relay fixture did not start')

    def run(self):
        self.loop=asyncio.new_event_loop();asyncio.set_event_loop(self.loop)
        async def start():
            self.server=await asyncio.start_server(self.relay.handle,'127.0.0.1',0,ssl=self.identity.context,limit=2048)
            self.port=self.server.sockets[0].getsockname()[1]
        self.loop.run_until_complete(start());self.ready.set();self.loop.run_forever()
        pending=asyncio.all_tasks(self.loop)
        for task in pending:task.cancel()
        self.loop.run_until_complete(asyncio.gather(*pending,return_exceptions=True));self.loop.close()

    def close(self):
        async def close():
            self.server.close();await self.server.wait_closed()
        asyncio.run_coroutine_threadsafe(close(),self.loop).result(timeout=5)
        self.loop.call_soon_threadsafe(self.loop.stop);self.thread.join(5)

    def wait_route(self,route):
        async def wait():
            for _ in range(100):
                if route in self.relay.routes and not self.relay.routes[route].joined.is_set():return True
                await asyncio.sleep(.05)
            return False
        return asyncio.run_coroutine_threadsafe(wait(),self.loop).result(timeout=6)
