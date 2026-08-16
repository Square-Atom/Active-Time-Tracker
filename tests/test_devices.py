"""Game-pad and MIDI activity.

The Windows APIs need real hardware, so the parts that decide *what counts as
input* are tested directly and the watchers are driven with fakes.
"""

import sys
import types

import devices
import pytest


# --- which MIDI messages mean a person did something ----------------------

@pytest.mark.parametrize("status,expected,why", [
    (0x90, True, "note on"),
    (0x80, True, "note off"),
    (0xB0, True, "control change"),
    (0xE0, True, "pitch bend"),
    (0xD0, True, "channel pressure"),
    (0x9F, True, "note on, channel 16"),
    (0xF8, False, "MIDI clock"),
    (0xFE, False, "active sensing"),
    (0xFA, False, "start"),
    (0xFC, False, "stop"),
    (0xFF, False, "reset"),
    (0xF0, False, "sysex"),
    (0x00, False, "data byte, not a status byte"),
])
def test_is_musical_message(status, expected, why):
    assert devices.is_musical_message(status) is expected, why


def test_realtime_chatter_is_ignored():
    """Keyboards emit clock and active sensing several times a second whether
    or not anyone is playing — counting them would mean never going idle."""
    assert not any(devices.is_musical_message(s) for s in range(0xF8, 0x100))


# --- controller snapshots ignore drift ------------------------------------

def _pad(buttons=0, lt=0, rt=0, lx=0, ly=0, rx=0, ry=0):
    return types.SimpleNamespace(
        wButtons=buttons, bLeftTrigger=lt, bRightTrigger=rt,
        sThumbLX=lx, sThumbLY=ly, sThumbRX=rx, sThumbRY=ry)


def test_small_stick_drift_does_not_count_as_input():
    snap = devices._ControllerWatcher.snapshot
    assert snap(_pad(lx=0)) == snap(_pad(lx=1500)), "drift should be ignored"
    assert snap(_pad(rt=1)) == snap(_pad(rt=10)), "trigger jitter ignored"


def test_a_real_nudge_is_noticed():
    snap = devices._ControllerWatcher.snapshot
    assert snap(_pad(lx=0)) != snap(_pad(lx=20000))
    assert snap(_pad(buttons=0)) != snap(_pad(buttons=0x1000)), "A button"
    assert snap(_pad(rt=0)) != snap(_pad(rt=255)), "trigger pulled"


# --- how activity is reported ---------------------------------------------

@pytest.fixture
def activity(monkeypatch):
    """A DeviceActivity with both backends stubbed out."""
    act = devices.DeviceActivity()
    monkeypatch.setattr(act.controllers, "poll", lambda: False)
    monkeypatch.setattr(act.midi, "start", lambda: 0)
    monkeypatch.setattr(act.midi, "stop", lambda: None)
    return act


def test_reports_never_when_nothing_has_happened(activity):
    activity.start()
    assert activity.seconds_since_input() == devices.NEVER


def test_controller_input_resets_the_clock(activity, monkeypatch):
    activity.start()
    monkeypatch.setattr(activity.controllers, "poll", lambda: True)
    assert activity.seconds_since_input() < 1.0


def test_midi_input_resets_the_clock(activity, monkeypatch):
    import time
    monkeypatch.setattr(type(activity.midi), "open_ports",
                        property(lambda self: 1))
    activity.midi.last_input = time.monotonic()
    assert activity.seconds_since_input() < 1.0


def test_midi_ports_are_opened_once_and_only_once(monkeypatch):
    act = devices.DeviceActivity()
    calls = []
    monkeypatch.setattr(act.midi, "start", lambda: calls.append("start") or 1)
    monkeypatch.setattr(act.midi, "stop", lambda: calls.append("stop"))
    ports = {"n": 0}
    monkeypatch.setattr(type(act.midi), "open_ports",
                        property(lambda self: ports["n"]))

    act.start()
    assert calls == ["start"]
    ports["n"] = 1
    act.start()                     # called every tick; must not churn ports
    act.start()
    assert calls == ["start"]

    act.release()                   # pausing hands the ports back
    assert calls == ["start", "stop"]
    ports["n"] = 0
    act.release()                   # also called every tick while paused
    assert calls == ["start", "stop"]


# --- graceful behaviour off Windows ---------------------------------------

def test_everything_degrades_quietly_without_the_windows_apis(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    act = devices.DeviceActivity()
    assert act.controllers.available is False
    assert act.midi.available is False
    act.start()                                     # must not raise
    assert act.seconds_since_input() == devices.NEVER
    assert act.controllers.poll() is False
    act.close()


def test_an_old_config_with_the_removed_switches_still_loads(tmp_path,
                                                             monkeypatch):
    """1.4.x wrote count_controller_input / count_midi_input. Both are gone;
    a config still carrying them must load, and lose them when next saved."""
    import json, config
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"idle_timeout_seconds": 12,
                                "count_controller_input": False,
                                "count_midi_input": False}))
    monkeypatch.setattr(config, "CONFIG_PATH", str(path))

    cfg = config.load()
    assert cfg.idle_timeout_seconds == 12
    cfg.save()
    saved = json.loads(path.read_text())
    assert "count_midi_input" not in saved
    assert "count_controller_input" not in saved
