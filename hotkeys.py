"""The "new note" hotkey: its text form, capturing it, and keeping it registered.

A hotkey is stored as text such as ``"Ctrl+Alt+N"`` — modifiers in a fixed
order, then one key. Registering it with the OS goes through `sysinfo`, which
returns None where that isn't supported, so this module works everywhere.
"""

from __future__ import annotations

import logging
import sys

import sysinfo

MODIFIERS = ("Ctrl", "Alt", "Shift", "Win")

_NAMED_KEYS = ("Space", "PageUp", "PageDown", "End", "Home",
               "Left", "Up", "Right", "Down", "Insert", "Delete")

# Tk keysyms -> our key names, for keys whose names differ.
_TK_KEYSYMS = {"space": "Space", "Prior": "PageUp", "Next": "PageDown"}

# Tk keysyms for the modifier keys themselves.
_TK_MODIFIER_KEYSYMS = {
    "Control_L": "Ctrl", "Control_R": "Ctrl",
    "Alt_L": "Alt", "Alt_R": "Alt", "Meta_L": "Alt", "Meta_R": "Alt",
    "Shift_L": "Shift", "Shift_R": "Shift",
    "Win_L": "Win", "Win_R": "Win", "Super_L": "Win", "Super_R": "Win",
}


def _is_function_key(key: str) -> bool:
    return key[:1] == "F" and key[1:].isdigit() and 1 <= int(key[1:]) <= 24


def _valid_key(key: str) -> bool:
    return ((len(key) == 1 and key.isascii() and key.isalnum())
            or _is_function_key(key) or key in _NAMED_KEYS)


def parse(spec: str) -> tuple[frozenset[str], str] | None:
    """``"ctrl + alt + n"`` -> ({"Ctrl", "Alt"}, "N"), or None if unusable.

    A plain key needs at least one modifier, or typing it anywhere would
    trigger the hotkey. Function keys may stand alone.
    """
    parts = [p.strip() for p in (spec or "").split("+")]
    if not parts or not all(parts):
        return None
    lookup = {m.lower(): m for m in MODIFIERS}
    lookup.update({"control": "Ctrl", "super": "Win", "cmd": "Win"})
    mods: set[str] = set()
    for p in parts[:-1]:
        mod = lookup.get(p.lower())
        if mod is None:
            return None
        mods.add(mod)
    key = parts[-1]
    key = key.upper() if len(key) == 1 else \
        next((k for k in _NAMED_KEYS if k.lower() == key.lower()), key.upper())
    if not _valid_key(key):
        return None
    if not mods and not _is_function_key(key):
        return None
    return frozenset(mods), key


def format_spec(mods, key: str) -> str:
    return "+".join([m for m in MODIFIERS if m in mods] + [key])


def normalize(spec: str) -> str:
    """The canonical spelling of `spec`, or "" if it isn't a usable hotkey."""
    parsed = parse(spec)
    return format_spec(*parsed) if parsed else ""


def modifier_for_keysym(keysym: str) -> str | None:
    return _TK_MODIFIER_KEYSYMS.get(keysym)


def key_from_tk(keysym: str, keycode: int = 0) -> str | None:
    """Our name for a pressed Tk key, or None if it can't be a hotkey key."""
    key = _TK_KEYSYMS.get(keysym, keysym)
    if len(key) == 1:
        key = key.upper()
    if _valid_key(key):
        return key
    # With Shift held, Tk reports "exclam" rather than "1". On Windows the
    # keycode is the virtual-key code, which is the digit/letter itself.
    if sys.platform == "win32" and (0x30 <= keycode <= 0x39 or 0x41 <= keycode <= 0x5A):
        return chr(keycode)
    return None


class HotkeyManager:
    """Keeps at most one global hotkey registered, calling `callback` on it.

    The callback runs on a background thread — marshal to Tk with `after`.
    """

    def __init__(self, callback):
        self._callback = callback
        self._handle = None
        self.spec = ""

    @property
    def supported(self) -> bool:
        return sysinfo.HOTKEYS_SUPPORTED

    def set(self, spec: str) -> bool:
        """Register `spec` in place of the current hotkey ("" clears it).

        Returns False if it couldn't be registered — usually because another
        app already uses the combination.
        """
        spec = normalize(spec)
        if spec == self.spec and (self._handle or not spec):
            return True
        self.clear()
        if not spec:
            return True
        mods, key = parse(spec)
        try:
            self._handle = sysinfo.register_hotkey(mods, key, self._callback)
        except Exception:
            logging.exception("Could not register hotkey %s", spec)
            self._handle = None
        if self._handle is None:
            return False
        self.spec = spec
        return True

    def clear(self) -> None:
        if self._handle is not None:
            try:
                self._handle.stop()
            except Exception:
                logging.exception("Could not release hotkey %s", self.spec)
        self._handle = None
        self.spec = ""
