import hashlib
import hmac
import json
from pathlib import Path
import socket
import struct
import sys
import threading
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'windows'))
from protocol import read_exact
import wake
import tray_support

KEY='ab'*32
HOST='01'*16


class WakeTests(unittest.TestCase):
    def helper(self,operation,*,bad_mac=False,length=None):
        server,client=socket.socketpair();errors=[]
        def run():
            try:
                nonce=bytes(range(32));server.sendall(wake.MAGIC+nonce)
                size,=struct.unpack('!H',read_exact(server,2));identity=read_exact(server,size)
                opcode=read_exact(server,1);mac=read_exact(server,32)
                self.assertEqual(opcode,bytes([operation]))
                self.assertTrue(hmac.compare_digest(mac,hmac.new(bytes.fromhex(KEY),b'client\0'+nonce+identity+opcode,hashlib.sha256).digest()))
                body=b'{"status":"launch_requested","requestId":"fixture"}'
                signature=hmac.new(bytes.fromhex(KEY),b'server\0'+nonce+opcode+body,hashlib.sha256).digest()
                if bad_mac:signature=bytes(32)
                server.sendall(struct.pack('!I',len(body) if length is None else length))
                if length is None:
                    for chunk in (body[:2],body[2:],signature):server.sendall(chunk)
            except Exception as error:errors.append(error)
            finally:server.close()
        worker=threading.Thread(target=run);worker.start()
        return client,worker,errors

    def test_authenticated_operations_and_fragmented_reply(self):
        for op in (wake.AUTO,wake.RESUME,wake.STATUS):
            sock,worker,errors=self.helper(op)
            with sock:self.assertEqual(wake.request(sock,HOST,KEY,op)['status'],'launch_requested')
            worker.join(3);self.assertFalse(errors)

    def test_unverified_reply_cannot_trigger_success(self):
        sock,worker,errors=self.helper(wake.AUTO,bad_mac=True)
        with sock:
            with self.assertRaises(wake.WakeAuthenticationError):wake.request(sock,HOST,KEY)
        worker.join(3);self.assertFalse(errors)

    def test_length_limit(self):
        sock,worker,errors=self.helper(wake.AUTO,length=4097)
        with sock:
            with self.assertRaises(ValueError):wake.request(sock,HOST,KEY)
        worker.join(3);self.assertFalse(errors)

    def test_invalid_settings_do_not_touch_socket(self):
        for identity,key,op in [('x',KEY,0),(HOST,'00',0),(HOST,KEY,True),(HOST,KEY,3)]:
            with self.assertRaises(ValueError):wake.request(None,identity,key,op)

    def test_retry_budget_replug_and_explicit_resume(self):
        budget=wake.RetryBudget();budget.reset(('serial',1))
        self.assertTrue(budget.allow(0));self.assertFalse(budget.allow(.1))
        self.assertTrue(budget.allow(10));self.assertTrue(budget.allow(20));self.assertFalse(budget.allow(100))
        budget.reset(('serial',1));self.assertFalse(budget.allow(101))
        budget.reset(('serial',2));self.assertTrue(budget.allow(101))
        self.assertTrue(budget.allow(101.1,explicit=True))

    def test_startup_command_quotes_paths_and_keeps_background_flag(self):
        with patch.object(sys,'executable',r'C:\Program Files\Shock Stream\ShockStream.exe'),patch.object(sys,'frozen',True,create=True):
            self.assertEqual(tray_support.startup_command(),'"C:\\Program Files\\Shock Stream\\ShockStream.exe" --background')


if __name__=='__main__':unittest.main()
