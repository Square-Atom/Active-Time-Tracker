"""Thin ctypes wrappers around the Win32 APIs we need.

We deliberately avoid global keyboard/mouse hooks (which some antivirus tools
flag and which require care to run safely). Instead we poll:

  * GetForegroundWindow  -> which window has focus
  * GetWindowTextW       -> its title (used to parse the open file)
  * GetWindowThreadProcessId + QueryFullProcessImageNameW -> the owning .exe
  * GetLastInputInfo     -> system-wide idle time (seconds since last input)

Combining "current foreground app" with "seconds since last input" lets us
credit active time to whatever app was focused, without installing hooks.
"""

from __future__ import annotations

import ctypes
import os
from ctypes import wintypes
from dataclasses import dataclass

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

# --- function signatures -------------------------------------------------

user32.GetForegroundWindow.restype = wintypes.HWND
user32.GetForegroundWindow.argtypes = []

user32.GetWindowTextLengthW.restype = ctypes.c_int
user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]

user32.GetWindowTextW.restype = ctypes.c_int
user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]

user32.GetWindowThreadProcessId.restype = wintypes.DWORD
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]

kernel32.OpenProcess.restype = wintypes.HANDLE
kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]

kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
kernel32.QueryFullProcessImageNameW.argtypes = [
    wintypes.HANDLE,
    wintypes.DWORD,
    wintypes.LPWSTR,
    ctypes.POINTER(wintypes.DWORD),
]

kernel32.CloseHandle.restype = wintypes.BOOL
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]

kernel32.GetTickCount.restype = wintypes.DWORD
kernel32.GetTickCount.argtypes = []

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000


class LASTINPUTINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]


user32.GetLastInputInfo.restype = wintypes.BOOL
user32.GetLastInputInfo.argtypes = [ctypes.POINTER(LASTINPUTINFO)]


SPI_GETWORKAREA = 0x0030
user32.SystemParametersInfoW.restype = wintypes.BOOL
user32.SystemParametersInfoW.argtypes = [wintypes.UINT, wintypes.UINT,
                                         ctypes.c_void_p, wintypes.UINT]


def work_area() -> tuple[int, int, int, int] | None:
    """The desktop minus the taskbar, as (left, top, right, bottom)."""
    rect = wintypes.RECT()
    if not user32.SystemParametersInfoW(SPI_GETWORKAREA, 0,
                                        ctypes.byref(rect), 0):
        return None
    return rect.left, rect.top, rect.right, rect.bottom


@dataclass
class WindowInfo:
    hwnd: int
    title: str
    exe: str  # basename, lowercased, e.g. "photoshop.exe"
    pid: int


def get_idle_seconds() -> float:
    """Seconds since the last keyboard or mouse input, system-wide."""
    info = LASTINPUTINFO()
    info.cbSize = ctypes.sizeof(info)
    if not user32.GetLastInputInfo(ctypes.byref(info)):
        return 0.0
    # GetTickCount and dwTime are both 32-bit ms since boot; subtraction wraps
    # correctly modulo 2**32 (49.7 days), which is fine for a 10s threshold.
    millis = (kernel32.GetTickCount() - info.dwTime) & 0xFFFFFFFF
    return millis / 1000.0


def _process_name(pid: int) -> str:
    if not pid:
        return ""
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return ""
    try:
        size = wintypes.DWORD(1024)
        buf = ctypes.create_unicode_buffer(size.value)
        if kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
            return os.path.basename(buf.value).lower()
        return ""
    finally:
        kernel32.CloseHandle(handle)


def get_foreground_window() -> WindowInfo | None:
    """Return info about the currently focused top-level window, or None."""
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return None

    length = user32.GetWindowTextLengthW(hwnd)
    buf = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buf, length + 1)
    title = buf.value

    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    exe = _process_name(pid.value)

    return WindowInfo(hwnd=int(hwnd), title=title, exe=exe, pid=pid.value)


# --- global hotkey -------------------------------------------------------
# RegisterHotKey asks Windows to post us a message for one key combination.
# Unlike a keyboard hook it never sees any other keystroke.

MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000
WM_HOTKEY = 0x0312
WM_QUIT = 0x0012
PM_NOREMOVE = 0x0000

user32.RegisterHotKey.restype = wintypes.BOOL
user32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
user32.UnregisterHotKey.restype = wintypes.BOOL
user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
user32.GetMessageW.restype = wintypes.BOOL
user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND,
                               wintypes.UINT, wintypes.UINT]
user32.PeekMessageW.restype = wintypes.BOOL
user32.PeekMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND,
                                wintypes.UINT, wintypes.UINT, wintypes.UINT]
user32.PostThreadMessageW.restype = wintypes.BOOL
user32.PostThreadMessageW.argtypes = [wintypes.DWORD, wintypes.UINT,
                                      wintypes.WPARAM, wintypes.LPARAM]
kernel32.GetCurrentThreadId.restype = wintypes.DWORD
kernel32.GetCurrentThreadId.argtypes = []


class GlobalHotkey:
    """One system-wide hotkey, served by a thread with its own message loop.

    A hotkey belongs to the thread that registered it, so registering,
    waiting and unregistering all happen on that thread.
    """

    _ID = 1

    def __init__(self, modifiers: int, vk: int, callback):
        import threading
        self._modifiers = modifiers | MOD_NOREPEAT
        self._vk = vk
        self._callback = callback
        self._ready = threading.Event()
        self._ok = False
        self._thread_id = 0
        self._thread = threading.Thread(target=self._run, name="hotkey", daemon=True)

    def start(self) -> bool:
        """Register the hotkey. False if another app already owns it."""
        self._thread.start()
        self._ready.wait(timeout=2)
        return self._ok

    def stop(self) -> None:
        if self._thread_id and self._thread.is_alive():
            user32.PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)
            self._thread.join(timeout=2)

    def _run(self) -> None:
        import logging
        msg = wintypes.MSG()
        # Makes sure the thread has a message queue before anyone posts to it.
        user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, PM_NOREMOVE)
        self._thread_id = kernel32.GetCurrentThreadId()
        self._ok = bool(user32.RegisterHotKey(None, self._ID, self._modifiers, self._vk))
        self._ready.set()
        if not self._ok:
            return
        try:
            while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                if msg.message == WM_HOTKEY:
                    try:
                        self._callback()
                    except Exception:
                        logging.exception("Hotkey handler failed")
        finally:
            user32.UnregisterHotKey(None, self._ID)
