import ctypes as C
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'windows'))
import usb_presence as presence

IPAD = '0123456789abcdef0123456789abcdef01234567'
OTHER = 'abcdef0123456789abcdef0123456789abcdef01'


def parent(serial=IPAD, product='12AB'):
    return 'USB\\VID_05AC&PID_' + product + '\\' + serial


class FakeSetupAPI:
    def __init__(self, identities=(), enum_error=None, id_error=None, invalid_handle=False):
        self.identities = list(identities)
        self.enum_error, self.id_error = enum_error, id_error
        self.invalid_handle = invalid_handle
        self.last_error = 0
        self.destroyed = []
        self.class_requests = []
        self.capacities = []
        self.struct_sizes = []

    def SetupDiGetClassDevsW(self, guid, enumerator, owner, flags):
        self.class_requests.append((guid, enumerator, owner, flags))
        return C.c_void_p(-1).value if self.invalid_handle else 123

    def SetupDiEnumDeviceInfo(self, handle, index, pointer):
        if self.enum_error is not None and index == self.enum_error[0]:
            self.last_error = self.enum_error[1]
            return False
        if index >= len(self.identities):
            self.last_error = presence.ERROR_NO_MORE_ITEMS
            return False
        info = C.cast(pointer, C.POINTER(presence.SP_DEVINFO_DATA)).contents
        self.struct_sizes.append(info.cbSize)
        info.DevInst = index
        self.last_error = 0
        return True

    def SetupDiGetDeviceInstanceIdW(self, handle, device, buffer, capacity, needed):
        index = C.cast(device, C.POINTER(presence.SP_DEVINFO_DATA)).contents.DevInst
        self.capacities.append(capacity)
        if self.id_error is not None and index == self.id_error[0]:
            self.last_error = self.id_error[1]
            return False
        identity = self.identities[index]
        C.cast(needed, C.POINTER(presence.DWORD)).contents.value = len(identity) + 1
        if capacity < len(identity) + 1:
            self.last_error = presence.ERROR_INSUFFICIENT_BUFFER
            return False
        buffer.value = identity
        self.last_error = 0
        return True

    def SetupDiDestroyDeviceInfoList(self, handle):
        self.destroyed.append(handle)
        return True


class NativePresenceTests(unittest.TestCase):
    def test_selected_legacy_serial_is_case_insensitive(self):
        api = FakeSetupAPI([parent(IPAD.upper())])
        self.assertIs(presence.apple_usb_present(IPAD, api), True)
        self.assertEqual(api.class_requests, [(None, 'USB', None, 6)])
        self.assertEqual(api.struct_sizes, [C.sizeof(presence.SP_DEVINFO_DATA)])
        self.assertEqual(api.destroyed, [123])

    def test_hyphens_are_normalized_on_both_sides(self):
        serial = '00008030-001A23456789ABCD'
        self.assertIs(presence.apple_usb_present(serial.replace('-', '').lower(), FakeSetupAPI([parent(serial)])), True)
        self.assertIs(presence.apple_usb_present(serial, FakeSetupAPI([parent(serial.replace('-', ''))])), True)

    def test_amds_is_not_consulted_for_presence(self):
        # A present Windows USB node remains conclusive even if usbmux/AMDS is absent.
        with patch.dict(sys.modules, {'usbmux': None}):
            self.assertIs(presence.apple_usb_present(IPAD, FakeSetupAPI([parent()])), True)

    def test_missing_selected_device_is_false_even_with_another_apple_device(self):
        self.assertIs(presence.apple_usb_present(IPAD, FakeSetupAPI([parent(OTHER)])), False)

    def test_unselected_one_device_is_true_but_multiple_are_unknown(self):
        self.assertIs(presence.apple_usb_present(None, FakeSetupAPI([parent()])), True)
        self.assertIs(presence.apple_usb_present(None, FakeSetupAPI([parent(), parent(OTHER)])), None)
        self.assertIs(presence.apple_usb_present(IPAD, FakeSetupAPI([parent(), parent(OTHER)])), True)

    def test_empty_snapshot_and_other_vendors_are_absent(self):
        for values in ([], ['USB\\VID_1234&PID_12AB\\' + IPAD],
                       ['USB\\VID_05AC0&PID_12AB\\' + IPAD], ['PCI\\VID_05AC&PID_12AB\\' + IPAD]):
            with self.subTest(values=values):
                self.assertIs(presence.apple_usb_present(IPAD, FakeSetupAPI(values)), False)

    def test_composite_interfaces_do_not_count_as_more_devices(self):
        interfaces = ['USB\\VID_05AC&PID_12AB&MI_00\\6&55555555&0&0000',
                      'USB\\VID_05AC&PID_12AB&MI_02\\6&55555555&0&0002']
        self.assertIs(presence.apple_usb_present(None, FakeSetupAPI([parent(), *interfaces])), True)
        self.assertIs(presence.apple_usb_present(IPAD, FakeSetupAPI(interfaces)), None)
        self.assertIs(presence.apple_usb_present(None, FakeSetupAPI(interfaces)), None)

    def test_duplicate_serial_nodes_are_one_device(self):
        values = [parent(IPAD.upper(), '12AB'), parent(IPAD, '12A8')]
        self.assertIs(presence.apple_usb_present(None, FakeSetupAPI(values)), True)

    def test_unidentifiable_parent_does_not_imply_selected_device_is_absent(self):
        api = FakeSetupAPI(['USB\\VID_05AC&PID_12AB\\5&123456&0&8'])
        self.assertIs(presence.apple_usb_present(IPAD, api), None)

    def test_get_instance_id_capacity_is_a_character_count(self):
        long_identity = 'USB\\VID_1234&PID_0001\\' + 'x' * 300
        api = FakeSetupAPI([long_identity, parent()])
        self.assertIs(presence.apple_usb_present(IPAD, api), True)
        self.assertEqual(api.capacities[:2], [256, len(long_identity) + 1])

    def test_oversized_identifier_is_unknown_and_handle_is_released(self):
        api = FakeSetupAPI(['USB\\VID_05AC&PID_0001\\' + 'f' * 5000])
        self.assertIs(presence.apple_usb_present(IPAD, api), None)
        self.assertEqual(api.destroyed, [123])

    def test_enumeration_error_never_counts_as_detachment(self):
        for error in (0, 5, 1167):
            api = FakeSetupAPI([parent()], enum_error=(0, error))
            with self.subTest(error=error):
                self.assertIs(presence.apple_usb_present(IPAD, api), None)
                self.assertEqual(api.destroyed, [123])

    def test_mid_snapshot_property_failure_is_unknown(self):
        api = FakeSetupAPI([parent(OTHER), parent()], id_error=(1, 1167))
        self.assertIs(presence.apple_usb_present(IPAD, api), None)
        self.assertEqual(api.destroyed, [123])

    def test_invalid_handle_does_not_get_destroyed(self):
        api = FakeSetupAPI(invalid_handle=True)
        self.assertIs(presence.apple_usb_present(IPAD, api), None)
        self.assertEqual(api.destroyed, [])

    def test_invalid_selected_serial_is_unknown_without_enumerating(self):
        for serial in ('', 'serial&port', '../ipad', 123, ' ffff ', '-fff', 'fff-'):
            api = FakeSetupAPI([parent()])
            with self.subTest(serial=serial):
                self.assertIs(presence.apple_usb_present(serial, api), None)
                self.assertEqual(api.class_requests, [])

    def test_malformed_apple_instance_is_unknown(self):
        for identity in ('USB\\VID_05AC&PID_12AB', 'USB\\VID_05AC&PID_12AB\\'):
            with self.subTest(identity=identity):
                self.assertIs(presence.apple_usb_present(None, FakeSetupAPI([identity])), None)


class AttachmentTrackerTests(unittest.TestCase):
    def test_existing_cable_at_start_never_resumes_pause(self):
        tracker = presence.AttachmentTracker()
        self.assertEqual([tracker.observe(value) for value in (None, True, True, None, True)], [False] * 5)

    def test_witnessed_detach_then_attach_emits_once(self):
        tracker = presence.AttachmentTracker()
        self.assertEqual([tracker.observe(value) for value in (True, False, False, True, True)],
                         [False, False, False, True, False])

    def test_unknown_does_not_erase_a_witnessed_detachment(self):
        tracker = presence.AttachmentTracker()
        self.assertEqual([tracker.observe(value) for value in (False, None, None, True)],
                         [False, False, False, True])

    def test_unknown_does_not_create_a_false_detachment(self):
        tracker = presence.AttachmentTracker()
        self.assertEqual([tracker.observe(value) for value in (True, None, True)], [False] * 3)
        self.assertIs(tracker.present, True)

    def test_logical_mux_device_id_changes_have_no_effect(self):
        tracker = presence.AttachmentTracker()
        for mux_id in (1, 7, 11, 22):
            with self.subTest(mux_id=mux_id):
                self.assertFalse(tracker.observe(True))

    def test_invalid_presence_value_is_rejected_without_changing_state(self):
        tracker = presence.AttachmentTracker()
        tracker.observe(False)
        with self.assertRaises(ValueError):
            tracker.observe('unknown')
        self.assertIs(tracker.present, False)


if __name__ == '__main__':
    unittest.main()
