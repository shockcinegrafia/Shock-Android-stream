import ctypes as C
import plistlib
import socket
import struct
import sys
from pathlib import Path
import threading
import time
import json
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'windows'))
import usbmux
from protocol import read_exact
from protocol import read_packet,packet,INFO,VIDEO,TOUCH,ACK,BYE
from host import Session
from touchscreen import TouchScreen,POINTER_TOUCH_INFO,POINTER_INFO,DOWN,UP,UPDATE,CANCELED,validate_events,TouchInjectionError

class FakeTouchAPI:
    def __init__(self):self.frames=[]
    def InitializeTouchInjection(self,count,visual):return True
    def InjectTouchInput(self,count,frame):
        self.frames.append([(i.pointerInfo.pointerId,i.pointerInfo.pointerFlags,
                             i.pointerInfo.ptPixelLocation.x,i.pointerInfo.ptPixelLocation.y) for i in frame])
        return True

class TouchTests(unittest.TestCase):
    def setUp(self):
        self.api=FakeTouchAPI();self.touch=TouchScreen(self.api)
        self.touch.set_monitor({'left':-1024,'top':200,'width':1024,'height':768})

    def event(self,ident,action,x=0.5,y=0.5):return dict(id=ident,a=action,x=x,y=y)

    def test_win64_abi(self):
        self.assertEqual(C.sizeof(POINTER_INFO),96)
        self.assertEqual(C.sizeof(POINTER_TOUCH_INFO),144)

    def test_monitor_offset_and_edges(self):
        self.assertEqual(self.touch.position(0,0),(-1024,200))
        self.assertEqual(self.touch.position(1,1),(-1,967))

    def test_short_stationary_tap_includes_update_and_zero_raw_coordinates(self):
        original=self.api.InjectTouchInput
        def validate(count,frame):
            for contact in frame:
                self.assertEqual((contact.pointerInfo.ptPixelLocationRaw.x,contact.pointerInfo.ptPixelLocationRaw.y),(0,0))
            return original(count,frame)
        self.api.InjectTouchInput=validate
        self.touch.events([self.event(0,'down'),self.event(0,'up')])
        self.assertEqual(len(self.api.frames),3)
        self.assertTrue(self.api.frames[1][0][1]&UPDATE)
        self.assertTrue(self.api.frames[2][0][1]&UP)

    def test_not_ready_retries_the_same_frame(self):
        original=self.api.InjectTouchInput;attempts=[]
        def flaky(count,frame):
            attempts.append(bytes(frame))
            if len(attempts)==1:C.set_last_error(21);return False
            return original(count,frame)
        self.api.InjectTouchInput=flaky
        self.touch.events([self.event(0,'down')])
        self.assertEqual(attempts[0],attempts[1]);self.assertEqual(len(self.api.frames),1)

    def test_native_error_code_is_preserved(self):
        def denied(count,frame):C.set_last_error(87);return False
        self.api.InjectTouchInput=denied
        with self.assertRaises(TouchInjectionError) as failure:self.touch.events([self.event(0,'down')])
        self.assertEqual(failure.exception.code,87)

    def test_two_fingers_keep_other_contact_on_release(self):
        self.touch.events([self.event(0,'down'),self.event(1,'down')])
        self.assertEqual(len(self.api.frames[-1]),2)
        self.touch.events([self.event(0,'up')])
        terminal=self.api.frames[-1]
        self.assertTrue(terminal[0][1]&UP)
        self.assertTrue(terminal[1][1]&UPDATE)
        self.assertEqual(set(self.touch.contacts),{1})

    def test_terminal_coordinate_update_precedes_up(self):
        self.touch.events([self.event(0,'down',0,0),self.event(0,'up',1,1)])
        self.assertTrue(self.api.frames[-2][0][1]&UPDATE)
        self.assertTrue(self.api.frames[-1][0][1]&UP)
        self.assertEqual(self.api.frames[-2][0][2:],self.api.frames[-1][0][2:])

    def test_simultaneous_moves_are_one_native_frame(self):
        self.touch.events([self.event(0,'down'),self.event(1,'down')]);before=len(self.api.frames)
        self.touch.events([self.event(0,'move',0.2,0.3),self.event(1,'move',0.8,0.7)])
        self.assertEqual(len(self.api.frames),before+1)
        self.assertEqual(self.api.frames[-1][0][2:],self.touch.position(0.2,0.3))
        self.assertEqual(self.api.frames[-1][1][2:],self.touch.position(0.8,0.7))

    def test_cancel_and_watchdog(self):
        self.touch.events([self.event(0,'down')]);self.touch.last=time.monotonic()-1;self.touch.expire()
        self.assertTrue(self.api.frames[-1][0][1]&CANCELED)
        self.assertFalse(self.touch.contacts)

    def test_validate_whole_batch_before_injecting(self):
        with self.assertRaises(ValueError):self.touch.events([self.event(0,'down'),self.event(1,'move',float('nan'))])
        self.assertFalse(self.api.frames)

class USBTests(unittest.TestCase):
    def server(self,callback):
        left,right=socket.socketpair()
        def serve():
            try:
                size,version,kind,tag=usbmux.HEADER.unpack(read_exact(left,16))
                request=plistlib.loads(read_exact(left,size-16));reply=callback(request)
                body=plistlib.dumps(reply);left.sendall(usbmux.HEADER.pack(16+len(body),1,8,tag)+body)
            finally:left.close()
        thread=threading.Thread(target=serve);thread.start();return right,thread

    def test_filter_network_devices(self):
        sock,thread=self.server(lambda request:{'DeviceList':[
            {'DeviceID':1,'Properties':{'ConnectionType':'Network'}},
            {'DeviceID':2,'Properties':{'ConnectionType':'USB','SerialNumber':'test'}}]})
        with patch.object(usbmux.socket,'create_connection',return_value=sock):devices=usbmux.list_devices()
        thread.join();self.assertEqual([d['DeviceID'] for d in devices],[2])

    def test_usb_connect_port_byte_order(self):
        captured=[]
        def callback(request):captured.append(request);return {'MessageType':'Result','Number':0}
        sock,thread=self.server(callback)
        with patch.object(usbmux.socket,'create_connection',return_value=sock):connection=usbmux.connect_device(7)
        thread.join();connection.close()
        self.assertEqual(captured[0]['DeviceID'],7)
        self.assertEqual(socket.ntohs(captured[0]['PortNumber']),8091)

    def test_usb_closed_port_is_reported(self):
        sock,thread=self.server(lambda request:{'MessageType':'Result','Number':3})
        with patch.object(usbmux.socket,'create_connection',return_value=sock):
            with self.assertRaisesRegex(ConnectionError,'Aguardar PC'):usbmux.connect_device(7)
        thread.join()

class TouchSessionTests(unittest.TestCase):
    def test_input_rejection_reports_notice_and_video_remains_connected(self):
        from protocol import NOTICE
        import numpy as np
        api=FakeTouchAPI();original=api.InjectTouchInput;attempts=[]
        def once(count,frame):
            attempts.append(1)
            if len(attempts)==1:C.set_last_error(87);return False
            return original(count,frame)
        api.InjectTouchInput=once;touch=TouchScreen(api)
        touch.set_monitor(dict(left=0,top=0,width=128,height=72))
        left,right=socket.socketpair();left.settimeout(3);right.settimeout(3)
        session=Session(left,touch,30,1024,False,lambda _:None,'touch')
        def capture():
            session.width,session.height=128,72
            while not session.stop.is_set():
                session.latest.put(np.zeros((72,128,4),dtype=np.uint8));session.stop.wait(.01)
        session.capture=capture;errors=[]
        def run():
            try:session.run()
            except Exception as error:errors.append(error)
        worker=threading.Thread(target=run);worker.start()
        try:
            self.assertEqual(read_packet(right)[0],INFO);self.assertEqual(read_packet(right)[0],VIDEO)
            right.sendall(packet(TOUCH,b'[{"id":0,"a":"down","x":0.5,"y":0.5}]'));right.sendall(packet(ACK))
            notices=[]
            while True:
                kind,body=read_packet(right)
                if kind==VIDEO:break
                self.assertEqual(kind,NOTICE);notices.append(json.loads(body))
            self.assertEqual(notices[0]['code'],87);self.assertTrue(notices[0]['recoverable'])
            self.assertTrue(worker.is_alive());right.sendall(packet(BYE));worker.join(4)
            self.assertFalse(worker.is_alive());self.assertFalse(errors);self.assertFalse(touch.contacts)
        finally:session.close();right.close();worker.join(4)

    def test_touch_session_routes_input_without_gamepad(self):
        import numpy as np
        api=FakeTouchAPI();touch=TouchScreen(api)
        touch.set_monitor({'left':-128,'top':0,'width':128,'height':72})
        left,right=socket.socketpair();left.settimeout(3);right.settimeout(3)
        session=Session(left,touch,30,1024,False,lambda _:None,'touch')
        def capture():
            session.width,session.height=128,72
            while not session.stop.is_set():
                session.latest.put(np.zeros((72,128,4),dtype=np.uint8));session.stop.wait(0.01)
        session.capture=capture;errors=[]
        def run():
            try:session.run()
            except Exception as error:errors.append(error)
        worker=threading.Thread(target=run);worker.start()
        kind,body=read_packet(right);self.assertEqual(kind,INFO)
        self.assertEqual(json.loads(body)['mode'],'touch')
        self.assertEqual(read_packet(right)[0],VIDEO)
        events=[dict(id=0,a='down',x=0,y=0),dict(id=0,a='move',x=1,y=1),dict(id=0,a='up',x=1,y=1)]
        right.sendall(packet(TOUCH,json.dumps(events).encode()));right.sendall(packet(ACK))
        self.assertEqual(read_packet(right)[0],VIDEO);right.sendall(packet(BYE))
        worker.join(4);right.close();self.assertFalse(worker.is_alive());self.assertFalse(errors)
        self.assertTrue(api.frames[0][0][1]&DOWN)
        self.assertTrue(api.frames[-1][0][1]&UP)
        self.assertFalse(touch.contacts)

if __name__=='__main__':unittest.main()
