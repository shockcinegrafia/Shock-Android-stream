"""Read physical Apple USB presence without depending on Apple Mobile Device Service.

Only SetupAPI's PRESENT USB device nodes are inspected; nothing is installed or
changed. Unknown/incomplete enumeration must never be mistaken for detachment.
"""
import ctypes as C
import re

DWORD = C.c_uint32
WORD = C.c_uint16
DIGCF_PRESENT = 0x2
DIGCF_ALLCLASSES = 0x4
ERROR_INSUFFICIENT_BUFFER = 122
ERROR_NO_MORE_ITEMS = 259
MAX_INSTANCE_CHARACTERS = 4096
MAX_DEVICES = 4096


class GUID(C.Structure):
    _fields_ = [('Data1', DWORD), ('Data2', WORD), ('Data3', WORD), ('Data4', C.c_ubyte * 8)]


class SP_DEVINFO_DATA(C.Structure):
    _fields_ = [('cbSize', DWORD), ('ClassGuid', GUID), ('DevInst', DWORD), ('Reserved', C.c_size_t)]


def _api(api):
    if api is not None:
        return api
    api = C.WinDLL('setupapi', use_last_error=True)
    api.SetupDiGetClassDevsW.argtypes = [C.c_void_p, C.c_wchar_p, C.c_void_p, DWORD]
    api.SetupDiGetClassDevsW.restype = C.c_void_p
    api.SetupDiEnumDeviceInfo.argtypes = [C.c_void_p, DWORD, C.POINTER(SP_DEVINFO_DATA)]
    api.SetupDiEnumDeviceInfo.restype = C.c_int
    api.SetupDiGetDeviceInstanceIdW.argtypes = [C.c_void_p, C.POINTER(SP_DEVINFO_DATA),
                                             C.c_wchar_p, DWORD, C.POINTER(DWORD)]
    api.SetupDiGetDeviceInstanceIdW.restype = C.c_int
    api.SetupDiDestroyDeviceInfoList.argtypes = [C.c_void_p]
    api.SetupDiDestroyDeviceInfoList.restype = C.c_int
    return api


def _last_error(api):
    error = getattr(api, 'last_error', None)
    return error if error is not None else getattr(C, 'get_last_error', lambda: 0)()


def _instance_id(api, handle, device):
    capacity = 256
    for _ in range(3):
        buffer = C.create_unicode_buffer(capacity)
        needed = DWORD()
        if api.SetupDiGetDeviceInstanceIdW(handle, C.byref(device), buffer, capacity, C.byref(needed)):
            return buffer.value if buffer.value else None
        if _last_error(api) != ERROR_INSUFFICIENT_BUFFER:
            return None
        # SetupAPI reports WCHAR counts here, not byte lengths.
        if not capacity < needed.value <= MAX_INSTANCE_CHARACTERS:
            return None
        capacity = needed.value
    return None


def _instances(api):
    handle = api.SetupDiGetClassDevsW(None, 'USB', None, DIGCF_PRESENT | DIGCF_ALLCLASSES)
    if getattr(handle, 'value', handle) in (None, 0, C.c_void_p(-1).value):
        return None
    values = []
    try:
        for index in range(MAX_DEVICES):
            device = SP_DEVINFO_DATA()
            device.cbSize = C.sizeof(device)
            if not api.SetupDiEnumDeviceInfo(handle, index, C.byref(device)):
                return values if _last_error(api) == ERROR_NO_MORE_ITEMS else None
            identity = _instance_id(api, handle, device)
            if identity is None:
                return None  # A device vanished mid-snapshot or a property could not be read.
            values.append(identity)
        return None
    finally:
        api.SetupDiDestroyDeviceInfoList(handle)


def normalized_serial(serial):
    """Match usbmux's legacy 40-hex UDIDs and newer hyphenated hex identifiers."""
    if not isinstance(serial, str) or not 1 <= len(serial) <= 128:
        return None
    if not re.fullmatch(r'[0-9a-fA-F]+(?:-[0-9a-fA-F]+)*', serial):
        return None
    return serial.replace('-', '').lower()


def apple_usb_present(serial=None, api=None):
    """Return True/False/None for a selected serial, or a sole Apple USB device.

    None means enumeration failed or the identity is ambiguous. For serial=None,
    multiple physical Apple device nodes are ambiguous. Composite MI_xx nodes
    are interfaces of a device, not additional physical cable attachments.
    """
    selected = normalized_serial(serial) if serial is not None else None
    if serial is not None and selected is None:
        return None
    try:
        values = _instances(_api(api))
        if values is None:
            return None
        parents = {}
        interface_only = False
        for value in values:
            parts = value.split('\\')
            if len(parts) < 2 or parts[0].upper() != 'USB' or not re.match(r'^VID_05AC(?:&|$)', parts[1], re.I):
                continue
            if re.search(r'(?:^|&)MI_[0-9A-F]{2}(?:&|$)', parts[1], re.I):
                interface_only = True
                continue
            if len(parts) != 3 or not parts[2]:
                return None
            found = normalized_serial(parts[2])
            # The same serial may have several class nodes, but is one device.
            parents[found if found else value.upper()] = found
        if selected is not None:
            if selected in parents.values():
                return True
            if any(value is None for value in parents.values()):
                return None  # An Apple parent without a usable serial could be the selected iPad.
            if not parents and interface_only:
                return None
            return False
        if not parents:
            return None if interface_only else False
        return True if len(parents) == 1 else None
    except (OSError, AttributeError, TypeError, ValueError):
        return None


class AttachmentTracker:
    """Emit only a witnessed absent -> present edge, preserving state on unknown."""
    def __init__(self):
        self.present = None

    def observe(self, present):
        if present is None:
            return False
        if present is not True and present is not False:
            raise ValueError('Presença USB deve ser True, False ou None')
        attached = self.present is False and present is True
        self.present = present
        return attached
