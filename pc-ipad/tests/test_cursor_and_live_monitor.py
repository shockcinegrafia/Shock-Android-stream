import ctypes as C
import json
from pathlib import Path
import socket
import sys
import threading
import time
import unittest
from unittest.mock import Mock,patch
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'windows'))
from cursor_capture import CursorRenderer,clipped_cursor,CURSORINFO
from video_options import StreamStats,bitrate
from host import Session,make_encoder
from protocol import INFO,VIDEO,ACK,BYE,read_packet,packet

class CursorTests(unittest.TestCase):
    def test_hotspot_negative_monitor_and_clipping(self):
        m=dict(left=-128,top=20,width=128,height=72)
        self.assertEqual(clipped_cursor(m,-126,22,4,4,32,32),(0,0,30,30,-2,-2))
        self.assertIsNone(clipped_cursor(m,100,100,0,0,32,32))
        self.assertEqual(clipped_cursor(m,-1,91,0,0,32,32),(127,71,128,72,0,0))

    @unittest.skipUnless(sys.platform=='win32','Windows GDI required')
    def test_real_windows_cursor_renders_and_releases_resources(self):
        renderer=CursorRenderer()
        renderer.user.LoadCursorW.argtypes=[C.c_void_p,C.c_void_p];renderer.user.LoadCursorW.restype=C.c_void_p
        icon=renderer.user.LoadCursorW(None,C.c_void_p(32512))
        try:
            for background in (0,128,255):
                image=np.full((64,64,4),background,dtype=np.uint8)
                monitor=dict(left=-100,top=0,width=64,height=64)
                self.assertTrue(renderer.draw_icon(image,monitor,icon,-92,8))
                self.assertTrue(np.any(image[8:48,8:48,:3]!=background))
                self.assertTrue(np.all(image[:4,:,:3]==background))
                before=image.copy()
                self.assertFalse(renderer.draw_icon(image,monitor,icon,1000,1000))
                np.testing.assert_array_equal(image,before)
            def cursor_info(pointer):
                value=C.cast(pointer,C.POINTER(CURSORINFO)).contents
                value.flags=1;value.hCursor=icon;value.ptScreenPos.x=-92;value.ptScreenPos.y=8
                return 1
            with patch.object(renderer.user,'GetCursorInfo',side_effect=cursor_info):
                image=np.full((64,64,4),128,dtype=np.uint8)
                self.assertTrue(renderer.apply(image,monitor))
                self.assertTrue(np.any(image[:,:,:3]!=128))
        finally:renderer.close()
        self.assertIsNone(renderer.bitmap);self.assertIsNone(renderer.dc)

    def test_quality_profiles_encode_baseline_without_delayed_frames(self):
        import av
        for quality,expected in [('balanced',2500000),('text',5000000),('economy',1500000)]:
            encoder=make_encoder(128,72,30,quality)
            self.assertEqual(bitrate(quality),expected)
            self.assertEqual(encoder.bit_rate,expected)
            image=av.VideoFrame.from_ndarray(np.zeros((72,128,3),dtype=np.uint8),format='rgb24').reformat(format='yuv420p')
            data=b''.join(bytes(p) for p in encoder.encode(image));self.assertTrue(data)
            self.assertEqual(len(av.CodecContext.create('h264','r').decode(av.Packet(data))),1)
        with self.assertRaises(ValueError):bitrate('invalid')

    def test_statistics_measure_delivered_frames_and_ack(self):
        stats=StreamStats(0)
        self.assertIsNone(stats.record(1,100000,.04,.01))
        value=stats.record(2,100000,.06,.02)
        self.assertEqual(value['fps'],1);self.assertEqual(value['mbps'],.8)
        self.assertAlmostEqual(value['ack_ms'],50);self.assertAlmostEqual(value['encode_ms'],15)
        self.assertIsNone(stats.record(3,1,.001,.001))

class LiveMonitorTests(unittest.TestCase):
    def test_capture_recovers_display_change_and_refreshes_touch_rectangle(self):
        from mss.exception import ScreenShotError
        from types import SimpleNamespace
        monitor=dict(device='primary',virtual=False,left=0,top=0,width=128,height=72)
        inventory=[monitor];state=SimpleNamespace(failures=2,opened=0)
        class Capture:
            def __enter__(self):state.opened+=1;return self
            def __exit__(self,*args):self.close()
            def close(self):pass
            def grab(self,rect):
                if state.failures:state.failures-=1;raise ScreenShotError('Display changed')
                return np.zeros((rect['height'],rect['width'],4),dtype=np.uint8)
        left,right=socket.socketpair();touch=Mock()
        session=Session(left,touch,30,1024,False,lambda _:None,'touch',monitor,show_cursor=False)
        with patch('mss.mss',side_effect=Capture),patch('desktop.monitors',side_effect=lambda:inventory):
            worker=threading.Thread(target=session.capture);worker.start()
            try:
                sequence,raw=session.latest.take_after(0,2);self.assertIsNotNone(raw)
                changed=dict(monitor,left=-200,top=-20,width=104,height=60);inventory[0]=changed;state.failures=1
                deadline=time.monotonic()+3
                while time.monotonic()<deadline:
                    sequence,next_frame=session.latest.take_after(sequence,.2)
                    if next_frame is not None:raw=next_frame
                    if raw[1:3]==(104,60):break
                self.assertEqual(raw[1:3],(104,60));self.assertGreaterEqual(state.opened,4)
                touch.set_monitor.assert_called_with(changed)
                self.assertFalse(session.stop.is_set());self.assertIsNone(session.capture_error)
            finally:session.stop.set();worker.join(3);session.close();right.close()

    def test_main_virtual_video_options_and_touch_geometry_share_one_connection(self):
        import av
        virtual=dict(device='virtual',virtual=True,left=-128,top=0,width=128,height=72)
        primary=dict(device='primary',virtual=False,left=0,top=0,width=96,height=64)
        touch=Mock();errors=[]
        left,right=socket.socketpair();left.settimeout(3);right.settimeout(3)
        session=Session(left,touch,30,1024,False,lambda _:None,'touch',virtual,show_cursor=False)
        class Capture:
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def grab(self,rect):return np.zeros((rect['height'],rect['width'],4),dtype=np.uint8)
        def run():
            try:session.run()
            except Exception as error:errors.append(error)
        def next_info():
            for _ in range(50):
                kind,body=read_packet(right)
                if kind==INFO:return json.loads(body)
                self.assertEqual(kind,VIDEO);right.sendall(packet(ACK))
            self.fail('no geometry update')
        with patch('mss.mss',return_value=Capture()),patch('desktop.monitors',return_value=[virtual,primary]),patch('desktop.set_ipad_resolution',side_effect=lambda monitor,*args:monitor):
            worker=threading.Thread(target=run);worker.start()
            try:
                self.assertEqual(next_info()['width'],128);self.assertEqual(read_packet(right)[0],VIDEO)
                session.change_monitor(primary)
                self.assertFalse(session.geometry_ready.is_set());right.sendall(packet(ACK))
                self.assertEqual(next_info()['width'],96)
                kind,body=read_packet(right);self.assertEqual(kind,VIDEO)
                frame=av.CodecContext.create('h264','r').decode(av.Packet(body))[0]
                self.assertEqual((frame.width,frame.height),(96,64));self.assertFalse(session.geometry_ready.is_set())
                right.sendall(packet(ACK));self.assertTrue(session.geometry_ready.wait(2));touch.set_monitor.assert_called_with(primary)
                session.configure_video(20,640,'text')
                info=next_info();self.assertEqual(info['fps'],20);self.assertEqual(read_packet(right)[0],VIDEO)
                session.change_monitor(virtual);right.sendall(packet(ACK))
                self.assertEqual(next_info()['width'],128);self.assertEqual(read_packet(right)[0],VIDEO)
                self.assertTrue(worker.is_alive());right.sendall(packet(BYE));worker.join(4)
                self.assertFalse(worker.is_alive());self.assertFalse(errors)
            finally:session.close();right.close();worker.join(4)
