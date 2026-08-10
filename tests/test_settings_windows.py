"""The editor windows: Settings, Ignored apps, and App groups."""

import os
import types

import autostart
import config
import pytest
import updatedialog
import updater
from ignoreapps import IgnoreWindow
from merges import MergesWindow
from settings import SettingsWindow


@pytest.fixture(autouse=True)
def no_registry_writes(monkeypatch):
    """Never touch the real login-items registry/plist from a test."""
    monkeypatch.setattr(autostart, "set_enabled", lambda enabled: None)
    monkeypatch.setattr(autostart, "is_enabled", lambda: False)


@pytest.fixture
def settings(tk_root, cfg, store):
    tracker = types.SimpleNamespace(cfg=cfg)
    win = SettingsWindow(tk_root, cfg, tracker, storage=store)
    tk_root.update_idletasks()
    yield win
    try:
        win.close()
    except Exception:
        pass


def test_saves_intervals_and_toggles(settings, cfg, tk_root):
    settings.idle_var.set("25")
    settings.poll_var.set("0.5")
    settings.check_updates_var.set(False)
    settings.backup_var.set(False)
    settings._save()

    assert cfg.idle_timeout_seconds == 25
    assert cfg.poll_interval_seconds == 0.5
    assert cfg.check_updates_on_startup is False
    assert cfg.backup_enabled is False


def test_out_of_range_values_are_clamped(settings, cfg):
    settings.idle_var.set("1")        # below the 2s minimum
    settings.poll_var.set("999")      # above the 10s maximum
    settings._save()
    assert cfg.idle_timeout_seconds == 2
    assert cfg.poll_interval_seconds == 10


def test_nonsense_input_is_rejected_without_saving(settings, cfg, monkeypatch):
    import tkinter.messagebox as mb
    shown = []
    monkeypatch.setattr(mb, "showerror", lambda *a, **k: shown.append(a))
    before = cfg.idle_timeout_seconds
    settings.idle_var.set("banana")
    settings._save()
    assert shown, "the user should be told the value is invalid"
    assert cfg.idle_timeout_seconds == before


def test_default_backup_dir_is_stored_as_empty(settings, cfg):
    """Storing "" keeps the default portable if the data dir ever moves."""
    settings.backup_path_var.set(os.path.join(config.APP_DIR, "backups"))
    settings._save()
    assert cfg.backup_dir == ""


def test_custom_backup_dir_is_kept(settings, cfg, tmp_path):
    settings.backup_path_var.set(str(tmp_path / "synced"))
    settings._save()
    assert cfg.backup_dir == str(tmp_path / "synced")


def test_backup_now_writes_a_file(settings, cfg, store, tmp_path, today, tk_root):
    store.add_seconds(today, "code.exe", "VS Code", "main.py", 10)
    settings.backup_path_var.set(str(tmp_path / "bk"))
    settings._backup_now()
    tk_root.update_idletasks()
    assert "Saved" in settings.backup_status.cget("text")
    assert (tmp_path / "bk" / f"data-{today}.db").exists()


def test_manual_update_check_shows_a_result(settings, tk_root, monkeypatch):
    shown = {}
    monkeypatch.setattr(updatedialog, "show_result",
                        lambda parent, res: shown.update(status=res.status))
    monkeypatch.setattr(updater, "check_async",
                        lambda cb, v=None: cb(updater.UpdateResult(
                            "update", latest="9.9.9")))
    settings._check_updates()
    for _ in range(5):
        tk_root.update(); tk_root.update_idletasks()
    assert shown.get("status") == "update"
    assert str(settings.update_btn.cget("state")) == "normal"


# --- ignored apps ----------------------------------------------------------

def test_ignore_window_add_and_remove(tk_root, store, today):
    store.add_seconds(today, "chrome.exe", "Chrome", "", 100)
    store.add_seconds(today, "game.exe", "Game", "", 200)
    cfg = config.Config(ignore_apps=["chrome.exe"])
    cfg.save = lambda: None  # type: ignore[method-assign]

    win = IgnoreWindow(tk_root, cfg, store)
    tk_root.update_idletasks()
    assert win.listbox.size() == 1
    assert all("chrome.exe" not in v for v in win.combo["values"]), \
        "already-ignored apps shouldn't be offered again"

    win.combo.set("game.exe")           # typed exe
    win._add()
    assert set(win.ignored) == {"chrome.exe", "game.exe"}

    win.listbox.selection_set(0)
    win._remove()
    win._save()
    assert cfg.ignore_apps == ["game.exe"]


# --- app groups ------------------------------------------------------------

def test_groups_window_saves_and_drops_empties(tk_root, store, cfg, today):
    store.add_seconds(today, "godot.exe", "Godot", "", 100)
    win = MergesWindow(tk_root, cfg, store)
    tk_root.update_idletasks()

    win._new_group()
    win.name_var.set("Godot")
    win._on_name_change()
    win.member_combo.set("godot.exe")
    win._add_member()
    win._new_group()                      # left empty on purpose
    win._save()

    assert cfg.merges == [{"name": "Godot", "members": ["godot.exe"]}]
