"""The polling loop: what gets credited, and what deliberately doesn't."""

import time

import config
import sysinfo
import tracker as tracker_mod
from storage import today_str


def _fake_window(monkeypatch, *, exe, title, pid=4321, idle=0.0):
    monkeypatch.setattr(sysinfo, "get_idle_seconds", lambda: idle)
    monkeypatch.setattr(sysinfo, "get_foreground_window",
                        lambda: sysinfo.WindowInfo(1, title, exe, pid))


def _run_briefly(tr, seconds=0.8):
    tr.start()
    time.sleep(seconds)
    tr.stop()


def _cfg(**kw):
    kw.setdefault("poll_interval_seconds", 0.1)
    kw.setdefault("flush_interval_seconds", 0.2)
    c = config.Config(**kw)
    c.save = lambda: None  # type: ignore[method-assign]
    return c


def test_active_time_is_credited_to_app_and_file(store, monkeypatch):
    _fake_window(monkeypatch, exe="photoshop.exe", title="poster.psd @ 50%")
    _run_briefly(tracker_mod.Tracker(store, _cfg()))

    day = today_str()
    apps = {a["app"]: a["seconds"] for a in store.totals_by_app(day, day)}
    assert apps.get("photoshop.exe", 0) > 0
    files = [f["file"] for f in store.totals_by_file(day, day, "photoshop.exe")]
    assert "poster.psd" in files


def test_idle_beyond_the_timeout_stops_the_clock(store, monkeypatch):
    _fake_window(monkeypatch, exe="photoshop.exe", title="poster.psd", idle=999)
    _run_briefly(tracker_mod.Tracker(store, _cfg(idle_timeout_seconds=10)))

    day = today_str()
    assert store.totals_by_app(day, day) == []


def test_own_window_is_labelled_as_the_app_not_the_interpreter(store, monkeypatch):
    import os
    _fake_window(monkeypatch, exe="pythonw.exe", title="Active Time Tracker",
                 pid=os.getpid())
    _run_briefly(tracker_mod.Tracker(store, _cfg()))

    day = today_str()
    apps = {a["app"]: a["app_name"] for a in store.totals_by_app(day, day)}
    assert apps.get(tracker_mod.OWN_APP_KEY) == "Active Time Tracker"
    assert "pythonw.exe" not in apps


def test_ignored_apps_are_never_recorded(store, monkeypatch):
    _fake_window(monkeypatch, exe="game.exe", title="Some Game")
    _run_briefly(tracker_mod.Tracker(store, _cfg(ignore_apps=["game.exe"])))

    day = today_str()
    assert store.totals_by_app(day, day) == []


def test_pausing_stops_crediting(store, monkeypatch):
    _fake_window(monkeypatch, exe="code.exe", title="a.py - p - Visual Studio Code")
    tr = tracker_mod.Tracker(store, _cfg())
    tr.set_paused(True)
    _run_briefly(tr)

    day = today_str()
    assert store.totals_by_app(day, day) == []


def test_config_changes_apply_without_restart(store, monkeypatch):
    """The loop re-reads config each tick, so settings take effect live."""
    _fake_window(monkeypatch, exe="chrome.exe", title="GitHub - Google Chrome")
    cfg = _cfg(ignore_apps=["chrome.exe"])
    tr = tracker_mod.Tracker(store, cfg)
    tr.start()
    time.sleep(0.4)
    day = today_str()
    assert store.totals_by_app(day, day) == []      # ignored so far

    cfg.ignore_apps = []                            # un-ignore mid-flight
    time.sleep(0.5)
    tr.stop()

    apps = {a["app"] for a in store.totals_by_app(day, day)}
    assert "chrome.exe" in apps


class _Watcher:
    """Stands in for notifications.FocusWatcher."""

    def __init__(self):
        self.ticks = []

    def tick(self, app_key, app_name, seconds):
        self.ticks.append((app_key, app_name, seconds))


def test_focus_time_is_reported_for_the_reminder_clock(store, monkeypatch):
    _fake_window(monkeypatch, exe="aseprite.exe", title="hero.aseprite")
    watcher = _Watcher()
    _run_briefly(tracker_mod.Tracker(store, _cfg(), watcher=watcher))
    assert watcher.ticks
    assert {t[0] for t in watcher.ticks} == {"aseprite.exe"}


def test_our_own_window_never_touches_the_reminder_clock(store, monkeypatch):
    """Nor does idle time — neither reaches the watcher at all."""
    import os
    _fake_window(monkeypatch, exe="pythonw.exe", title="Active Time Tracker",
                 pid=os.getpid())
    watcher = _Watcher()
    _run_briefly(tracker_mod.Tracker(store, _cfg(), watcher=watcher))
    assert watcher.ticks == []

    _fake_window(monkeypatch, exe="aseprite.exe", title="hero.aseprite", idle=999)
    _run_briefly(tracker_mod.Tracker(store, _cfg(idle_timeout_seconds=10),
                                     watcher=watcher))
    assert watcher.ticks == []


def test_credit_per_tick_is_capped(store, monkeypatch):
    """A sleep/wake gap must not dump a huge block onto whatever was focused."""
    _fake_window(monkeypatch, exe="code.exe", title="a.py - p - Visual Studio Code")
    cfg = _cfg(poll_interval_seconds=0.1)
    _run_briefly(tracker_mod.Tracker(store, cfg), seconds=0.6)

    day = today_str()
    total = store.grand_total(day, day)
    assert total <= 2.0, f"credited {total}s in ~0.6s of wall clock"
