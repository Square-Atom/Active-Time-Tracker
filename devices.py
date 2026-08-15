"""Activity from devices Windows doesn't count as "input".

`GetLastInputInfo` only sees keyboard and mouse, so playing a game on a pad or
a part on a MIDI keyboard looks like sitting idle and the timer stops. This
module watches those separately and reports how long since either was touched;
the tracker takes whichever source was most recent.

Windows-only for now — elsewhere it reports "never", which simply leaves the
keyboard/mouse behaviour unchanged.
"""

from __future__ import annotations

import ctypes
import logging
import sys
import time
from ctypes import wintypes

_log = logging.getLogger(__name__)

NEVER = float("inf")

# Sticks drift and knobs jitter, so raw values change constantly even when the
# pad is untouched. Quantising to this many steps ignores that without missing
# a real nudge.
_AXIS_STEP = 6000          # of a +/-32767 range
_TRIGGER_STEP = 24         # of a 0..255 range
_RESCAN_SECONDS = 5.0      # how often to look for newly plugged-in pads

# MIDI status bytes 0xF8..0xFF are System Real-Time: clock, active sensing and
# friends, which many keyboards emit several times a second whether or not
# anyone is playing. Counting those would make the app think you never stop.
_SYSTEM_REALTIME = 0xF8
MIM_DATA = 0x3C3
MIM_LONGDATA = 0x3C4
_CALLBACK_FUNCTION = 0x00030000
_MMSYSERR_ALLOCATED = 4


def is_musical_message(status: int) -> bool:
    """Whether a MIDI status byte means a person did something."""
    if status >= _SYSTEM_REALTIME:      # clock / active sensing / reset
        return False
    if status >= 0xF0:                  # other system messages
        return False
    return status >= 0x80               # note, control, pitch bend, …


class _ControllerWatcher:
    """Polls XInput. Read-only and never exclusive, so it can't disturb games."""

    def __init__(self):
        self._xinput = None
        self._state_cls = None
        self._snapshots: dict[int, tuple] = {}
        self._connected: set[int] = set()
        self._last_scan = 0.0
        self._load()

    def _load(self) -> None:
        if sys.platform != "win32":
            return
        for name in ("xinput1_4", "xinput1_3", "xinput9_1_0"):
            try:
                self._xinput = ctypes.WinDLL(name)
                break
            except OSError:
                continue
        if self._xinput is None:
            _log.info("No XInput available; controller input won't be counted")
            return

        class XINPUT_GAMEPAD(ctypes.Structure):
            _fields_ = [("wButtons", wintypes.WORD),
                        ("bLeftTrigger", ctypes.c_ubyte),
                        ("bRightTrigger", ctypes.c_ubyte),
                        ("sThumbLX", ctypes.c_short), ("sThumbLY", ctypes.c_short),
                        ("sThumbRX", ctypes.c_short), ("sThumbRY", ctypes.c_short)]

        class XINPUT_STATE(ctypes.Structure):
            _fields_ = [("dwPacketNumber", wintypes.DWORD),
                        ("Gamepad", XINPUT_GAMEPAD)]

        self._state_cls = XINPUT_STATE

    @property
    def available(self) -> bool:
        return self._xinput is not None

    @staticmethod
    def snapshot(gamepad) -> tuple:
        """Coarse view of a pad, ignoring drift and jitter."""
        return (
            gamepad.wButtons,
            gamepad.bLeftTrigger // _TRIGGER_STEP,
            gamepad.bRightTrigger // _TRIGGER_STEP,
            gamepad.sThumbLX // _AXIS_STEP, gamepad.sThumbLY // _AXIS_STEP,
            gamepad.sThumbRX // _AXIS_STEP, gamepad.sThumbRY // _AXIS_STEP,
        )

    def poll(self) -> bool:
        """True when a pad moved since the last call."""
        if not self.available:
            return False
        now = time.monotonic()
        # Querying an empty slot is slow, so only hunt for new pads now and then.
        if now - self._last_scan >= _RESCAN_SECONDS:
            self._last_scan = now
            slots = range(4)
        else:
            slots = tuple(self._connected)

        changed = False
        state = self._state_cls()
        for i in slots:
            if self._xinput.XInputGetState(i, ctypes.byref(state)) != 0:
                self._connected.discard(i)
                self._snapshots.pop(i, None)
                continue
            self._connected.add(i)
            snap = self.snapshot(state.Gamepad)
            previous = self._snapshots.get(i)
            self._snapshots[i] = snap
            # A pad appearing isn't input; only a change from a known state is.
            if previous is not None and snap != previous:
                changed = True
        return changed


class _MidiWatcher:
    """Opens every MIDI input and notes when a musical message arrives.

    Ports already held by something else are skipped rather than fought over,
    and each port is opened independently so one refusal doesn't lose the rest.
    """

    def __init__(self):
        self._winmm = None
        self._handles: list[wintypes.HANDLE] = []
        self._proc = None            # keep a reference or ctypes frees it
        self.last_input = 0.0
        if sys.platform == "win32":
            try:
                self._winmm = ctypes.WinDLL("winmm")
            except OSError:
                _log.info("winmm unavailable; MIDI input won't be counted")

    @property
    def available(self) -> bool:
        return self._winmm is not None

    @property
    def open_ports(self) -> int:
        return len(self._handles)

    def start(self) -> int:
        if not self.available or self._handles:
            return len(self._handles)

        proto = ctypes.WINFUNCTYPE(
            None, wintypes.HANDLE, wintypes.UINT,
            ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)

        def _callback(_h, msg, _inst, param1, _param2):
            if msg != MIM_DATA:
                return
            if is_musical_message((param1 or 0) & 0xFF):
                self.last_input = time.monotonic()

        self._proc = proto(_callback)

        for index in range(self._winmm.midiInGetNumDevs()):
            handle = wintypes.HANDLE()
            res = self._winmm.midiInOpen(ctypes.byref(handle), index,
                                         self._proc, 0, _CALLBACK_FUNCTION)
            if res != 0:
                if res == _MMSYSERR_ALLOCATED:
                    _log.info("MIDI input %s is in use elsewhere; skipping", index)
                continue
            self._winmm.midiInStart(handle)
            self._handles.append(handle)
        if self._handles:
            _log.info("Watching %d MIDI input(s)", len(self._handles))
        return len(self._handles)

    def stop(self) -> None:
        for handle in self._handles:
            try:
                self._winmm.midiInStop(handle)
                self._winmm.midiInClose(handle)
            except Exception:
                pass
        self._handles.clear()
        self._proc = None


class DeviceActivity:
    """How long since a game pad or MIDI keyboard was touched."""

    def __init__(self):
        self.controllers = _ControllerWatcher()
        self.midi = _MidiWatcher()
        self._last_controller = 0.0

    def apply(self, *, controllers: bool, midi: bool) -> None:
        """Follow the current settings — called live, so toggles take effect."""
        if midi and not self.midi.open_ports:
            self.midi.start()
        elif not midi and self.midi.open_ports:
            self.midi.stop()
        self._controllers_on = controllers

    def seconds_since_input(self) -> float:
        """Smallest gap since any watched device was used; NEVER if none."""
        newest = 0.0
        if getattr(self, "_controllers_on", False):
            if self.controllers.poll():
                self._last_controller = time.monotonic()
            newest = max(newest, self._last_controller)
        if self.midi.open_ports:
            newest = max(newest, self.midi.last_input)
        if not newest:
            return NEVER
        return time.monotonic() - newest

    def close(self) -> None:
        self.midi.stop()
