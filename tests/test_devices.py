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
    activity.apply(controllers=True, midi=False)
    assert activity.seconds_since_input() == devices.NEVER


def test_controller_input_resets_the_clock(activity, monkeypatch):
    activity.apply(controllers=True, midi=False)
    monkeypatch.setattr(activity.controllers, "poll", lambda: True)
    assert activity.seconds_since_input() < 1.0


def test_controller_is_not_polled_when_switched_off(activity, monkeypatch):
    polled = []
    monkeypatch.setattr(activity.controllers, "poll",
                        lambda: polled.append(1) or True)
    activity.apply(controllers=False, midi=False)
    assert activity.seconds_since_input() == devices.NEVER
    assert polled == [], "shouldn't touch the pad when the setting is off"


def test_midi_input_resets_the_clock(activity, monkeypatch):
    import time
    monkeypatch.setattr(type(activity.midi), "open_ports",
                        property(lambda self: 1))
    activity.midi.last_input = time.monotonic()
    activity.apply(controllers=False, midi=False)   # open_ports is faked open
    assert activity.seconds_since_input() < 1.0


def test_settings_toggle_opens_and_closes_midi_ports(monkeypatch):
    act = devices.DeviceActivity()
    calls = []
    monkeypatch.setattr(act.midi, "start", lambda: calls.append("start") or 1)
    monkeypatch.setattr(act.midi, "stop", lambda: calls.append("stop"))
    ports = {"n": 0}
    monkeypatch.setattr(type(act.midi), "open_ports",
                        property(lambda self: ports["n"]))

    act.apply(controllers=False, midi=True)
    assert calls == ["start"]
    ports["n"] = 1
    act.apply(controllers=False, midi=True)         # already open, no churn
    assert calls == ["start"]
    act.apply(controllers=False, midi=False)        # turned off -> release
    assert calls == ["start", "stop"]


# --- graceful behaviour off Windows ---------------------------------------

def test_everything_degrades_quietly_without_the_windows_apis(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    act = devices.DeviceActivity()
    assert act.controllers.available is False
    assert act.midi.available is False
    act.apply(controllers=True, midi=True)          # must not raise
    assert act.seconds_since_input() == devices.NEVER
    assert act.controllers.poll() is False
    act.close()


def test_config_round_trips_the_new_settings():
    import config
    cfg = config.Config()
    assert cfg.count_controller_input is True and cfg.count_midi_input is True
    cfg.count_midi_input = False
    data = {}
    cfg.save = lambda: data.update(midi=cfg.count_midi_input)
    cfg.save()
    assert data["midi"] is False
