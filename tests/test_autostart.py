"""Login-item handling, especially keeping the stored path pointing at us.

The real registry isn't sandboxed by conftest, so Windows-specific reads are
mocked. The file-based backends (macOS/Linux) do write, but conftest redirects
HOME/XDG_CONFIG_HOME into a temp sandbox, so they land there.
"""

import sys

import autostart
import pytest


# --- ensure(): the decision logic, on every platform ----------------------

@pytest.fixture
def spy(monkeypatch):
    """Replace the platform calls so `ensure` can be tested in isolation."""
    state = {"exists": False, "matches": False, "set_calls": []}
    monkeypatch.setattr(autostart, "is_enabled", lambda: state["exists"])
    monkeypatch.setattr(autostart, "matches_current", lambda: state["matches"])
    monkeypatch.setattr(autostart, "set_enabled",
                        lambda enabled: state["set_calls"].append(enabled))
    return state


def test_enables_when_no_entry_exists(spy):
    assert autostart.ensure(True) is True
    assert spy["set_calls"] == [True]


def test_repairs_an_entry_that_points_somewhere_else(spy):
    """The bug this exists for: renaming or moving the exe leaves a stale
    entry that launches nothing, and 'it exists' would call that fine."""
    spy["exists"], spy["matches"] = True, False
    assert autostart.ensure(True) is True
    assert spy["set_calls"] == [True], "a stale entry must be rewritten"


def test_leaves_a_correct_entry_alone(spy):
    spy["exists"], spy["matches"] = True, True
    assert autostart.ensure(True) is False
    assert spy["set_calls"] == []


def test_removes_the_entry_when_disabled(spy):
    spy["exists"], spy["matches"] = True, True
    assert autostart.ensure(False) is True
    assert spy["set_calls"] == [False]


def test_does_nothing_when_disabled_and_absent(spy):
    assert autostart.ensure(False) is False
    assert spy["set_calls"] == []


# --- the launch command --------------------------------------------------

def test_launch_args_start_minimized():
    assert "--minimized" in autostart._launch_args()


def test_frozen_builds_launch_the_executable_itself(monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", r"C:\apps\ActiveTimeTracker-1.3.0.exe")
    assert autostart._launch_args() == [
        r"C:\apps\ActiveTimeTracker-1.3.0.exe", "--minimized"]


def test_matches_current_notices_a_renamed_executable(monkeypatch):
    """Rename the exe and the stored command should no longer match."""
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", r"C:\apps\Tracker-1.2.0.exe")
    if sys.platform == "win32":
        old = autostart._win_command()
        monkeypatch.setattr(sys, "executable", r"C:\apps\Tracker-1.3.0.exe")
        assert autostart._win_command() != old
    else:
        old = autostart._linux_desktop_entry() if sys.platform != "darwin" \
            else autostart._mac_plist()
        monkeypatch.setattr(sys, "executable", r"C:\apps\Tracker-1.3.0.exe")
        new = autostart._linux_desktop_entry() if sys.platform != "darwin" \
            else autostart._mac_plist()
        assert new != old


# --- real round-trip on the file-based backends --------------------------

@pytest.mark.skipif(sys.platform == "win32",
                    reason="Windows uses the registry, which isn't sandboxed")
def test_file_backend_round_trip(monkeypatch):
    assert autostart.is_enabled() is False
    autostart.set_enabled(True)
    assert autostart.is_enabled() is True
    assert autostart.matches_current() is True

    # a different executable path should stop matching …
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", "/opt/somewhere-else/tracker")
    assert autostart.matches_current() is False
    # … and ensure() should repair it
    assert autostart.ensure(True) is True
    assert autostart.matches_current() is True

    autostart.set_enabled(False)
    assert autostart.is_enabled() is False
