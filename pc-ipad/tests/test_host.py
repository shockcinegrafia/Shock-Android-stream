import hashlib
import hmac
import json
from pathlib import Path
import socket
import struct
import sys
import threading
import time
import unittest
from unittest.mock import patch
from enum import IntEnum
from types import SimpleNamespace

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"windows"))
from protocol import *
from host import Session, XboxPad, make_encoder


class FakeDevice:
    def reset(self): self.buttons=0;self.axes=(0,0,0,0);self.triggers=(0,0)
    def press_button(self,button): self.buttons |= int(button)
    def left_joystick_float(self,x_value_float,y_value_float): self.left=(x_value_float,y_value_float)
    def right_joystick_float(self,x_value_float,y_value_float): self.right=(x_value_float,y_value_float)
    def left_trigger_float(self,value_float): self.lt=value_float
    def right_trigger_float(self,value_float): self.rt=value_float
    def update(self): pass


class ProtocolTests(unittest.TestCase):
    def test_fragments(self):
        left,right=socket.socketpair()
        def send():
            for byte in packet(PAD,b'{"buttons":4096}'):
                left.sendall(bytes([byte]))
            left.close()
        thread=threading.Thread(target=send);thread.start()
        try:self.assertEqual(read_packet(right),(PAD,b'{"buttons":4096}'))
        finally:right.close();thread.join()

    def test_limit_before_allocation(self):
        left,right=socket.socketpair()
        left.sendall(HEADER.pack(VIDEO,MAX_PACKET+1))
        with self.assertRaises(ValueError):read_packet(right)
        left.close();right.close()

    def test_nonce_proof(self):
        self.assertEqual(proof('123456',bytes(range(32))),hmac.new(b'123456',bytes(range(32)),hashlib.sha256).digest())
        self.assertNotEqual(proof('123456',bytes(range(32))),proof('123456',b'0'*32))

    def test_latest_discards_old_captures(self):
        slot=LatestFrame()
        for i in range(100):slot.put(i)
        self.assertEqual(slot.take_after(0),(100,99))
        self.assertEqual(slot.take_after(100,0.001),(100,None))

    def test_dimensions_preserve_aspect(self):
        self.assertEqual(fit_size(1920,1080),(1024,576))
        self.assertEqual(fit_size(1080,1920),(576,1024))
        self.assertEqual(fit_size(800,600),(800,600))

    def test_pad_finite(self):
        self.assertEqual(validate_pad({'lx':4,'ry':-4,'lt':-2})['lx'],1)
        for invalid in ({'lx':float('nan')},{'rt':float('inf')},{'buttons':-1},{'buttons':True}):
            with self.assertRaises(ValueError):validate_pad(invalid)

    def test_button_release_and_watchdog(self):
        buttons=IntEnum('Buttons',{'UP':1,'A':4096,'B':8192,'LB':256})
        device=FakeDevice()
        fake=SimpleNamespace(XUSB_BUTTON=buttons,VX360Gamepad=lambda:device)
        with patch.dict(sys.modules,{'vgamepad':fake}):pad=XboxPad()
        pad.apply({'buttons':4097,'lx':0.5,'ly':-1,'rt':1})
        self.assertEqual(device.buttons,4097);self.assertEqual(device.left,(0.5,-1))
        pad.apply({'buttons':1});self.assertEqual(device.buttons,1)
        pad.last=time.monotonic()-1;pad.expire();self.assertEqual(device.buttons,0)


class CodecTests(unittest.TestCase):
    def test_h264_baseline_roundtrip(self):
        import av,numpy as np
        encoder=make_encoder(128,72,30);decoder=av.CodecContext.create('h264','r')
        for i in range(4):
            raw=np.full((72,128,3),i*40,dtype=np.uint8)
            frame=av.VideoFrame.from_ndarray(raw,format='rgb24').reformat(format='yuv420p');frame.pts=i
            encoded=b''.join(bytes(p) for p in encoder.encode(frame))
            self.assertTrue(encoded,'no frame buffering at encoder')
            frames=decoder.decode(av.Packet(encoded))
            self.assertEqual(len(frames),1)
            self.assertEqual((frames[0].width,frames[0].height),(128,72))
        # Verify the emitted SPS, rather than PyAV's unset encoder metadata.
        import re
        first=av.VideoFrame.from_ndarray(np.zeros((72,128,3),dtype=np.uint8),format='rgb24').reformat(format='yuv420p')
        baseline=make_encoder(128,72,30)
        data=b''.join(bytes(p) for p in baseline.encode(first))
        sps=next(n for n in re.split(b'\x00\x00\x00?\x01',data) if n and n[0]&31==7)
        self.assertEqual(sps[1],66,'H.264 Baseline profile_idc')
        self.assertTrue(sps[2]&0x40,'constrained baseline flag')

    def test_session_ack_and_control(self):
        import av,numpy as np
        left,right=socket.socketpair();left.settimeout(3);right.settimeout(3)
        pad=SimpleNamespace(states=[],neutral_count=0)
        pad.apply=lambda state:pad.states.append(validate_pad(state))
        pad.expire=lambda:None
        def neutral():pad.neutral_count+=1
        pad.neutral=neutral
        session=Session(left,pad,30,1024,False,lambda _:None)
        def capture():
            session.width,session.height=128,72
            while not session.stop.is_set():
                session.latest.put(np.zeros((72,128,4),dtype=np.uint8));session.stop.wait(0.005)
        session.capture=capture
        errors=[]
        def run():
            try:session.run()
            except Exception as error:errors.append(error)
        worker=threading.Thread(target=run);worker.start()
        self.assertEqual(read_packet(right)[0],INFO)
        self.assertEqual(read_packet(right)[0],VIDEO)
        right.sendall(packet(PAD,json.dumps({'buttons':4096,'lx':1}).encode()))
        right.settimeout(0.08)
        with self.assertRaises(socket.timeout):right.recv(1)
        self.assertGreater(session.latest.sequence,2,'capture continues overwriting while ACK waits')
        right.settimeout(3);right.sendall(packet(ACK));self.assertEqual(read_packet(right)[0],VIDEO)
        right.sendall(packet(PAD,b'{"buttons":0}'));right.sendall(packet(BYE));worker.join(4);right.close()
        self.assertFalse(worker.is_alive());self.assertFalse(errors)
        self.assertEqual([s['buttons'] for s in pad.states],[4096,0]);self.assertGreater(pad.neutral_count,0)


if __name__=='__main__':unittest.main()
