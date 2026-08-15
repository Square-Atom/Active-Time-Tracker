"""Closing the app captures a final backup before releasing the database."""

import os
import types

import backups
import main
import storage as storage_mod


def _cfg(tmp_path, **kw):
    import config
    c = config.Config(backup_dir=str(tmp_path / "bk"), **kw)
    c.save = lambda: None  # type: ignore[method-assign]
    return c


def _fake_tracker(store):
    calls = []
    return types.SimpleNamespace(stop=lambda: calls.append("stop")), calls


def test_quitting_backs_up_after_flushing(store, tmp_path, today):
    cfg = _cfg(tmp_path)
    store.add_seconds(today, "code.exe", "VS Code", "late.py", 300)  # unflushed
    tracker, calls = _fake_tracker(store)

    assert main.close_down(tracker, store, cfg, {}) is True
    assert calls == ["stop"], "tracking must stop before the backup"
    path = backups._db_path(cfg, today)
    assert storage_mod.describe_backup(path)["seconds"] == 300


def test_it_is_safe_to_call_twice(store, tmp_path, today):
    """Tray Quit and the mainloop unwinding both call this."""
    cfg = _cfg(tmp_path)
    store.add_seconds(today, "a.exe", "A", "", 60)
    tracker, calls = _fake_tracker(store)
    state: dict = {}

    assert main.close_down(tracker, store, cfg, state) is True
    assert main.close_down(tracker, store, cfg, state) is False, "should no-op"
    assert calls == ["stop"], "must not stop the tracker twice"


def test_the_database_is_closed_even_if_the_backup_fails(store, tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    monkeypatch.setattr(backups, "run_on_exit",
                        lambda *a: (_ for _ in ()).throw(OSError("drive gone")))
    tracker, _ = _fake_tracker(store)
    main.close_down(tracker, store, cfg, {})     # must not raise

    import sqlite3
    try:
        store._conn.execute("select 1")
        closed = False
    except sqlite3.ProgrammingError:
        closed = True
    assert closed, "the database should be closed even when the backup fails"


def test_backups_switched_off_means_no_file(store, tmp_path, today):
    cfg = _cfg(tmp_path, backup_enabled=False)
    store.add_seconds(today, "a.exe", "A", "", 10)
    tracker, _ = _fake_tracker(store)
    main.close_down(tracker, store, cfg, {})
    assert not os.path.exists(backups._db_path(cfg, today))
