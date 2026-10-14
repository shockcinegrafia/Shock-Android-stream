"""Resolution and aspect tests; never change a live Windows display."""
import ctypes as C
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'windows'))
from desktop import (CDS_TEST,DEVMODEW,DM_POSITION,ENUM_CURRENT_SETTINGS,
                     fit_target,set_ipad_resolution)

DEVICE=r'\\.\DISPLAY2'

def display_mode(width,height,frequency=60,left=-1024,top=80):
    mode=DEVMODEW();mode.dmSize=C.sizeof(mode)
    mode.dmPelsWidth=width;mode.dmPelsHeight=height;mode.dmDisplayFrequency=frequency
    mode.dmBitsPerPel=32;mode.dmPosition.x=left;mode.dmPosition.y=top
    return mode

class FakeDisplayAPI:
    def __init__(self,modes=None,test_result=0,apply_result=0):
        self.current=display_mode(1366,768)
        self.modes=modes if modes is not None else [display_mode(1024,768,75),display_mode(1024,768,60),display_mode(768,1024)]
        self.test_result=test_result;self.apply_result=apply_result;self.calls=[];self.enum_calls=[]

    def EnumDisplaySettingsW(self,device,index,pointer):
        self.enum_calls.append((device,index))
        mode=self.current if index==ENUM_CURRENT_SETTINGS else self.modes[index] if index<len(self.modes) else None
        if mode is None:return False
        C.memmove(pointer,C.byref(mode),C.sizeof(mode));return True

    def ChangeDisplaySettingsExW(self,device,pointer,window,flags,parameter):
        mode=DEVMODEW.from_buffer_copy(C.cast(pointer,C.POINTER(DEVMODEW)).contents)
        self.calls.append((device,mode,flags))
        result=self.test_result if flags==CDS_TEST else self.apply_result
        if not flags and not result:self.current=mode
        return result

    def monitors(self):
        return [dict(device=r'\\.\DISPLAY1',virtual=False,width=1920,height=1080,left=0,top=0),
                dict(device=DEVICE,virtual=True,width=int(self.current.dmPelsWidth),height=int(self.current.dmPelsHeight),
                     left=int(self.current.dmPosition.x),top=int(self.current.dmPosition.y))]

class FitTests(unittest.TestCase):
    def test_native_size_and_portrait_cap(self):
        self.assertEqual(fit_target(1024,768,1024,768),(1024,768))
        self.assertEqual(fit_target(768,1024,768,1024),(768,1024))
        self.assertEqual(fit_target(1920,1080,768,1024),(768,432))
        self.assertEqual(fit_target(1080,1920,1024,768),(432,768))

    def test_does_not_enlarge_and_caps_quality(self):
        self.assertEqual(fit_target(640,480,1024,768),(640,480))
        self.assertEqual(fit_target(1024,768,1024,768,800),(800,600))
        self.assertEqual(fit_target(1366,768,1024,768),(1024,574))

    def test_invalid_sizes_are_rejected(self):
        for sizes in ((0,768,1024,768),(1024,768,True,768),(1024,768,float('nan'),768),(1024,768,1024,float('inf'))):
            with self.subTest(sizes=sizes):
                with self.assertRaises(ValueError):fit_target(*sizes)

class DisplayModeTests(unittest.TestCase):
    def setUp(self):
        self.api=FakeDisplayAPI()
        self.monitor=dict(device=DEVICE,virtual=True,width=1366,height=768,left=-1024,top=80)

    def change(self,width=1024,height=768):
        return set_ipad_resolution(self.monitor,width,height,api=self.api,monitor_provider=self.api.monitors)

    @unittest.skipUnless(C.sizeof(C.c_wchar)==2,'Windows DEVMODEW ABI')
    def test_devmode_windows_layout(self):
        self.assertEqual(C.sizeof(DEVMODEW),220)
        self.assertEqual(DEVMODEW.dmFields.offset,72)
        self.assertEqual(DEVMODEW.dmPelsWidth.offset,172)
        self.assertEqual(DEVMODEW.dmDisplayFrequency.offset,184)

    def test_landscape_prefers_60hz_tests_then_applies_only_selected_device(self):
        result=self.change()
        self.assertEqual((result['width'],result['height']),(1024,768))
        self.assertEqual((result['left'],result['top']),(-1024,80))
        self.assertEqual([c[0] for c in self.api.calls],[DEVICE,DEVICE])
        self.assertEqual([c[2] for c in self.api.calls],[CDS_TEST,0])
        self.assertEqual(self.api.calls[-1][1].dmDisplayFrequency,60)
        self.assertFalse(self.api.calls[-1][1].dmFields&DM_POSITION)

    def test_rotation_changes_virtual_monitor_dimensions(self):
        result=self.change(768,1024)
        self.assertEqual((result['width'],result['height']),(768,1024))

    def test_fallback_uses_first_advertised_frequency(self):
        self.api.modes=[display_mode(1024,768,75),display_mode(1024,768,50)]
        self.change();self.assertEqual(self.api.calls[-1][1].dmDisplayFrequency,75)

    def test_physical_monitor_or_unsupported_dimensions_never_call_api(self):
        for monitor,width,height in ((dict(self.monitor,virtual=False),1024,768),
                                     (dict(self.monitor,virtual=1),1024,768),
                                     (self.monitor,1920,1080),(self.monitor,1024.0,768)):
            with self.subTest(monitor=monitor,width=width,height=height):
                with self.assertRaises(ValueError):
                    set_ipad_resolution(monitor,width,height,api=self.api,monitor_provider=self.api.monitors)
        self.assertFalse(self.api.enum_calls);self.assertFalse(self.api.calls)

    def test_failed_test_prevents_apply(self):
        self.api.test_result=-2
        with self.assertRaisesRegex(RuntimeError,'testar'):self.change()
        self.assertEqual([c[2] for c in self.api.calls],[CDS_TEST])

    def test_failed_apply_is_reported(self):
        self.api.apply_result=-1
        with self.assertRaisesRegex(RuntimeError,'aplicar'):self.change()

    def test_unadvertised_mode_never_changes_display(self):
        self.api.modes=[display_mode(1920,1080)]
        with self.assertRaisesRegex(RuntimeError,'não oferece'):self.change()
        self.assertFalse(self.api.calls)

    def test_already_correct_mode_is_not_reapplied(self):
        self.api.current=display_mode(1024,768)
        self.change();self.assertFalse(self.api.calls)

    def test_returned_geometry_must_belong_to_current_device_and_match(self):
        with self.assertRaisesRegex(RuntimeError,'não está mais disponível'):
            set_ipad_resolution(self.monitor,1024,768,api=self.api,monitor_provider=lambda:[])
        with self.assertRaisesRegex(RuntimeError,'ainda não confirmou'):
            set_ipad_resolution(self.monitor,1024,768,api=self.api,monitor_provider=lambda:[self.monitor])

if __name__=='__main__':unittest.main()
