"""Native window primitives. Never identify an app by title alone."""
import ctypes
import os
from ctypes import wintypes as W

U = ctypes.WinDLL('user32', use_last_error=True)
K = ctypes.WinDLL('kernel32', use_last_error=True)
LONG_PTR = ctypes.c_ssize_t
WNDENUM = ctypes.WINFUNCTYPE(W.BOOL, W.HWND, W.LPARAM)


def signature(module, name, result, *arguments):
    fn = getattr(module, name)
    fn.restype, fn.argtypes = result, list(arguments)
    return fn


for name, result, args in [
    ('EnumWindows', W.BOOL, [WNDENUM, W.LPARAM]), ('EnumChildWindows', W.BOOL, [W.HWND, WNDENUM, W.LPARAM]), ('IsWindow', W.BOOL, [W.HWND]),
    ('IsWindowVisible', W.BOOL, [W.HWND]), ('IsChild', W.BOOL, [W.HWND, W.HWND]),
    ('IsIconic', W.BOOL, [W.HWND]),
    ('GetWindowThreadProcessId', W.DWORD, [W.HWND, ctypes.POINTER(W.DWORD)]),
    ('GetWindowTextW', ctypes.c_int, [W.HWND, W.LPWSTR, ctypes.c_int]),
    ('GetClassNameW', ctypes.c_int, [W.HWND, W.LPWSTR, ctypes.c_int]),
    ('GetWindowLongPtrW', LONG_PTR, [W.HWND, ctypes.c_int]),
    ('SetWindowLongPtrW', LONG_PTR, [W.HWND, ctypes.c_int, LONG_PTR]),
    ('SetParent', W.HWND, [W.HWND, W.HWND]), ('GetParent', W.HWND, [W.HWND]),
    ('GetWindowRect', W.BOOL, [W.HWND, ctypes.POINTER(W.RECT)]),
    ('GetClientRect', W.BOOL, [W.HWND, ctypes.POINTER(W.RECT)]),
    ('ClientToScreen', W.BOOL, [W.HWND, ctypes.POINTER(W.POINT)]),
    ('SetWindowPos', W.BOOL, [W.HWND, W.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, W.UINT]),
    ('ShowWindow', W.BOOL, [W.HWND, ctypes.c_int]), ('SetForegroundWindow', W.BOOL, [W.HWND]),
    ('GetForegroundWindow', W.HWND, []), ('GetAncestor', W.HWND, [W.HWND, W.UINT]),
    ('GetWindow', W.HWND, [W.HWND, W.UINT]),
]:
    signature(U, name, result, *args)
signature(K, 'OpenProcess', W.HANDLE, W.DWORD, W.BOOL, W.DWORD)
signature(K, 'CloseHandle', W.BOOL, W.HANDLE)
signature(K, 'QueryFullProcessImageNameW', W.BOOL, W.HANDLE, W.DWORD, W.LPWSTR, ctypes.POINTER(W.DWORD))
signature(K, 'CreateToolhelp32Snapshot', W.HANDLE, W.DWORD, W.DWORD)
signature(K, 'GetApplicationUserModelId', W.LONG, W.HANDLE, ctypes.POINTER(W.UINT), W.LPWSTR)
signature(U, 'GetWindowDpiAwarenessContext', ctypes.c_void_p, W.HWND)
signature(U, 'AreDpiAwarenessContextsEqual', W.BOOL, ctypes.c_void_p, ctypes.c_void_p)
signature(U, 'SetThreadDpiAwarenessContext', ctypes.c_void_p, ctypes.c_void_p)
signature(U, 'GetDpiForWindow', W.UINT, W.HWND)


def physical():
    U.SetThreadDpiAwarenessContext(ctypes.c_void_p(-4))


def pid(hwnd):
    value = W.DWORD()
    U.GetWindowThreadProcessId(hwnd, ctypes.byref(value))
    return value.value


def executable(process_id):
    handle = K.OpenProcess(0x1000, False, process_id)
    if not handle:
        return ''
    try:
        size = W.DWORD(32768)
        buffer = ctypes.create_unicode_buffer(size.value)
        return buffer.value if K.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)) else ''
    finally:
        K.CloseHandle(handle)


def application_id(process_id):
    """Read packaged-app identity; launcher PID ancestry is not sufficient."""
    handle = K.OpenProcess(0x1000, False, process_id)
    if not handle:
        return ''
    try:
        size = W.UINT(0)
        if K.GetApplicationUserModelId(handle, ctypes.byref(size), None) != 122 or not 0 < size.value <= 32768:
            return ''
        value = ctypes.create_unicode_buffer(size.value)
        return value.value if K.GetApplicationUserModelId(handle, ctypes.byref(size), value) == 0 else ''
    finally:
        K.CloseHandle(handle)


def text(hwnd, kind='title'):
    buffer = ctypes.create_unicode_buffer(4096)
    (U.GetWindowTextW if kind == 'title' else U.GetClassNameW)(hwnd, buffer, len(buffer))
    return buffer.value


def window_app_ids(hwnd):
    # Packaged applications can be children of ApplicationFrameHost. Inspect
    # the actual child-process identities rather than matching a window title.
    processes = {pid(hwnd)}
    @WNDENUM
    def collect(child, _):
        processes.add(pid(child))
        return True
    U.EnumChildWindows(hwnd, collect, 0)
    return sorted({identity for process in processes if (identity := application_id(process))})


def bounds(hwnd, client=False):
    physical()
    rect = W.RECT()
    if not (U.GetClientRect if client else U.GetWindowRect)(hwnd, ctypes.byref(rect)):
        raise OSError('This application window is no longer available.')
    return [rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top]


def windows():
    physical()
    result = []
    @WNDENUM
    def collect(hwnd, _):
        title = text(hwnd)
        if U.IsWindowVisible(hwnd) and title:
            process_id = pid(hwnd)
            result.append({'hwnd': str(hwnd), 'pid': process_id, 'title': title, 'class': text(hwnd, 'class'), 'executable': executable(process_id), 'app_ids': window_app_ids(hwnd), 'owner': str(U.GetWindow(hwnd, 4) or 0)})
        return True
    U.EnumWindows(collect, 0)
    return result


def same_path(a, b):
    return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))


def process_tree(process_id):
    """Use real process ancestry to follow launchers without guessing by title."""
    class Entry(ctypes.Structure):
        _fields_ = [('size', W.DWORD), ('usage', W.DWORD), ('pid', W.DWORD),
                    ('heap', ctypes.c_size_t), ('module', W.DWORD), ('threads', W.DWORD),
                    ('parent', W.DWORD), ('priority', W.LONG), ('flags', W.DWORD), ('exe', W.WCHAR * 260)]
    signature(K, 'Process32FirstW', W.BOOL, W.HANDLE, ctypes.POINTER(Entry))
    signature(K, 'Process32NextW', W.BOOL, W.HANDLE, ctypes.POINTER(Entry))
    handle = K.CreateToolhelp32Snapshot(2, 0)
    if handle in (None, ctypes.c_void_p(-1).value):
        return {process_id}
    try:
        entry = Entry()
        entry.size = ctypes.sizeof(Entry)
        parents = {}
        more = K.Process32FirstW(handle, ctypes.byref(entry))
        while more:
            parents[entry.pid] = entry.parent
            more = K.Process32NextW(handle, ctypes.byref(entry))
        family = {process_id}
        for _ in range(32):
            updated = family | {pid for pid, parent in parents.items() if parent in family}
            if updated == family:
                break
            family = updated
        return family
    finally:
        K.CloseHandle(handle)


def present_capture(record):
    """Keep the capture source behind Vision, never parent/fit it over the UI."""
    physical()
    hwnd = int(record['hwnd'])
    if not U.IsWindow(hwnd):
        raise OSError('The application window closed.')
    if record.get('original'):
        detach(record)  # migrate a previously parented session before capturing
    record.setdefault('capture_original', {'topmost': bool(U.GetWindowLongPtrW(hwnd, -20) & 8)})
    if U.IsIconic(hwnd):
        U.ShowWindow(hwnd, 4)  # restore without taking focus; minimized captures can stop
    # HWND_BOTTOM + NOSIZE | NOMOVE | NOACTIVATE. No source-window resizing or
    # positioning is used to imitate an in-panel preview.
    if not U.SetWindowPos(hwnd, 1, 0, 0, 0, 0, 0x1 | 0x2 | 0x10):
        raise OSError('Windows could not keep the application behind the preview.')
    return {'mode': 'capture', 'reason': 'Live application view · rendered inside the preview'}


def detach(record):
    hwnd = int(record.get('hwnd') or 0)
    original = record.pop('original', None)
    capture_original = record.pop('capture_original', None)
    if not U.IsWindow(hwnd):
        return
    if original:
        U.SetParent(hwnd, original['parent'])
        U.SetWindowLongPtrW(hwnd, -16, original['style'])
        U.SetWindowLongPtrW(hwnd, -20, original['extended'])
        U.SetWindowPos(hwnd, 0, *original['bounds'], 0x20 | 0x10 | 0x40)
    if capture_original:
        U.SetWindowPos(hwnd, -1 if capture_original['topmost'] else -2, 0, 0, 0, 0, 0x1 | 0x2 | 0x10)
    record.pop('parent_hwnd', None)


class LASTINPUT(ctypes.Structure):
    _fields_ = [('size', W.UINT), ('tick', W.DWORD)]


def last_input():
    value = LASTINPUT(ctypes.sizeof(LASTINPUT), 0)
    U.GetLastInputInfo(ctypes.byref(value))
    return value.tick


def input_idle():
    return ((K.GetTickCount() & 0xffffffff) - last_input()) & 0xffffffff
