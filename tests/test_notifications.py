"""Focus reminders: when one is due, and the popup that delivers it."""

import config
import notifications
import pytest

THEME = {"bg": "#1e1f2b", "panel": "#272838", "fg": "#e8e8f0",
         "muted": "#9a9ab0", "accent": "#7c9cff"}


class Reminders(list):
    """Stands in for the callback, recording (app name, minutes)."""

    def __call__(self, app_name, minutes):
        self.append((app_name, minutes))


def _cfg(**kw) -> config.Config:
    kw.setdefault("notify_enabled", True)
    kw.setdefault("notify_first_minutes", 5)
    kw.setdefault("notify_repeat_minutes", 15)
    cfg = config.Config(**kw)
    cfg.save = lambda: None  # type: ignore[method-assign]
    return cfg


def _watcher(cfg=None):
    seen = Reminders()
    return notifications.FocusWatcher(cfg or _cfg(), seen), seen


def _focus(watcher, minutes, app="code.exe", name="VS Code"):
    """Spend `minutes` in one app, one 60-second tick at a time."""
    for _ in range(int(minutes)):
        watcher.tick(app, name, 60)


# --- when a reminder is due ------------------------------------------------

def test_nothing_is_said_before_the_first_reminder():
    watcher, seen = _watcher()
    _focus(watcher, 4)
    assert seen == []


def test_the_first_reminder_lands_on_time():
    watcher, seen = _watcher()
    _focus(watcher, 5)
    assert seen == [("VS Code", 5)]


def test_then_it_repeats_on_its_own_interval():
    watcher, seen = _watcher()
    _focus(watcher, 35)
    assert seen == [("VS Code", 5), ("VS Code", 20), ("VS Code", 35)]


def test_moving_to_another_app_starts_the_clock_over():
    watcher, seen = _watcher()
    _focus(watcher, 4)
    _focus(watcher, 4, app="chrome.exe", name="Chrome")
    assert seen == [], "neither app has had five minutes"
    _focus(watcher, 1, app="chrome.exe", name="Chrome")
    assert seen == [("Chrome", 5)]


def test_a_pause_in_the_ticks_freezes_rather_than_resets():
    """Idle time and our own windows simply stop feeding the watcher."""
    watcher, seen = _watcher()
    _focus(watcher, 4)
    # …an hour of idling or note-writing happens here, with no ticks at all…
    _focus(watcher, 1)
    assert seen == [("VS Code", 5)]


def test_switched_off_it_counts_but_keeps_quiet():
    cfg = _cfg(notify_enabled=False)
    watcher, seen = _watcher(cfg)
    _focus(watcher, 40)
    assert seen == []
    assert watcher.seconds == pytest.approx(40 * 60)


def test_switching_it_on_midway_reminds_once_not_a_backlog():
    cfg = _cfg(notify_enabled=False)
    watcher, seen = _watcher(cfg)
    _focus(watcher, 40)
    cfg.notify_enabled = True
    _focus(watcher, 1)
    assert seen == [("VS Code", 41)], "one reminder, naming the real total"
    _focus(watcher, 14)
    assert len(seen) == 1, "and the next one keeps to the interval"
    _focus(watcher, 1)
    assert seen[-1] == ("VS Code", 56)


def test_shortening_the_interval_takes_effect_without_a_restart():
    cfg = _cfg(notify_first_minutes=30)
    watcher, seen = _watcher(cfg)
    _focus(watcher, 10)
    assert seen == []
    cfg.notify_first_minutes = 5
    _focus(watcher, 1)
    assert seen == [("VS Code", 11)]


@pytest.mark.parametrize("value", ["", None, "soon"])
def test_a_nonsense_setting_falls_back_to_the_default(value):
    cfg = _cfg(notify_first_minutes=value)
    watcher, seen = _watcher(cfg)
    _focus(watcher, 4)
    assert seen == []
    _focus(watcher, 1)
    assert seen == [("VS Code", 5)]


def test_the_message_names_the_app_and_the_minutes():
    assert notifications.message("Aseprite", 5) == (
        "You have been focusing on Aseprite for 5 minutes.")
    assert "1 minute." in notifications.message("Blender", 1)


# --- the popup -------------------------------------------------------------

def test_the_toast_says_what_it_is_and_a_click_asks_for_a_note(tk_root):
    asked = []
    toast = notifications.Toast(tk_root, THEME, on_click=lambda: asked.append(1))
    toast.show("Aseprite", 5)
    tk_root.update_idletasks()

    assert toast.win is not None
    assert toast.text == "You have been focusing on Aseprite for 5 minutes."
    labels = [w.cget("text") for w in _labels(toast.win)]
    assert toast.text in labels
    assert notifications.Toast.PROMPT in labels

    toast._clicked()
    assert asked == [1]
    assert toast.win is None, "clicking dismisses it too"


def test_dismissing_the_toast_does_not_ask_for_a_note(tk_root):
    asked = []
    toast = notifications.Toast(tk_root, THEME, on_click=lambda: asked.append(1))
    toast.show("Blender", 20)
    tk_root.update_idletasks()

    toast._dismiss()
    assert asked == []
    assert toast.win is None


def test_a_second_reminder_replaces_the_first(tk_root):
    toast = notifications.Toast(tk_root, THEME)
    toast.show("Blender", 5)
    first = toast.win
    toast.show("Blender", 20)
    tk_root.update_idletasks()

    assert toast.win is not first
    assert not first.winfo_exists()
    assert "20 minutes" in toast.text


def test_the_toast_sits_inside_the_desktop_work_area(tk_root, monkeypatch):
    import sysinfo
    monkeypatch.setattr(sysinfo, "work_area", lambda: (0, 0, 1000, 800))
    toast = notifications.Toast(tk_root, THEME)
    toast.show("Krita", 5)
    tk_root.update_idletasks()

    win = toast.win
    right = win.winfo_x() + win.winfo_width()
    bottom = win.winfo_y() + win.winfo_height()
    assert right <= 1000 and bottom <= 800
    assert win.winfo_x() > 500, "bottom-right corner, not adrift in the middle"


def _labels(widget):
    """Every Label in a widget tree."""
    import tkinter as tk
    found = []
    for child in widget.winfo_children():
        if isinstance(child, tk.Label):
            found.append(child)
        found.extend(_labels(child))
    return found
