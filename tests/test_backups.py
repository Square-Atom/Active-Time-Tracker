"""Daily rotating backups: location, rotation, scheduling, and failure safety."""

import os

import backups
import config


def _cfg(tmp_path, **kw):
    c = config.Config(backup_dir=str(tmp_path / "bk"), **kw)
    c.save = lambda: None  # type: ignore[method-assign]
    return c


def test_default_location_is_inside_the_data_dir():
    c = config.Config()
    assert backups.backup_dir(c) == os.path.join(config.APP_DIR, "backups")


def test_custom_location_is_used_and_expanded():
    c = config.Config(backup_dir="~/somewhere/else")
    assert backups.backup_dir(c) == os.path.expanduser("~/somewhere/else")


def test_run_writes_db_and_config(store, tmp_path, today):
    store.add_seconds(today, "code.exe", "VS Code", "main.py", 30)
    c = _cfg(tmp_path)
    path = backups.run(store, c, today=today)
    assert path and os.path.exists(path)
    assert os.path.basename(path) == f"data-{today}.db"
    assert backups.existing(c) == [today]


def test_no_partial_file_is_left_behind(store, tmp_path, today):
    c = _cfg(tmp_path)
    backups.run(store, c, today=today)
    leftovers = [n for n in os.listdir(backups.backup_dir(c)) if n.endswith(".part")]
    assert leftovers == []


def test_rotation_keeps_only_the_newest(store, tmp_path):
    c = _cfg(tmp_path, backup_keep=3)
    for day in ("2026-01-01", "2026-01-02", "2026-01-03",
                "2026-01-04", "2026-01-05"):
        backups.run(store, c, today=day)
    assert backups.existing(c) == ["2026-01-05", "2026-01-04", "2026-01-03"]
    # pruning removes the paired config copies too
    names = os.listdir(backups.backup_dir(c))
    assert not any("2026-01-01" in n for n in names)


def test_is_due_only_once_a_day(store, tmp_path, today):
    c = _cfg(tmp_path)
    assert backups.is_due(c, today) is True
    backups.run(store, c, today=today)
    assert backups.is_due(c, today) is False
    assert backups.is_due(c, "2099-01-01") is True   # a later day is due again


def test_disabled_means_never_due(tmp_path, today):
    c = _cfg(tmp_path, backup_enabled=False)
    assert backups.is_due(c, today) is False


def test_maybe_run_is_idempotent_within_a_day(store, tmp_path):
    c = _cfg(tmp_path)
    assert backups.maybe_run(store, c) is not None
    assert backups.maybe_run(store, c) is None


def test_failure_is_swallowed_not_raised(store, tmp_path, monkeypatch, today):
    """A broken backup must never take the tracker down."""
    c = _cfg(tmp_path)

    def boom(_path):
        raise OSError("disk on fire")

    monkeypatch.setattr(store, "backup_to", boom)
    assert backups.run(store, c, today=today) is None   # logged, not raised


def test_unreadable_backup_dir_reports_nothing(tmp_path):
    c = _cfg(tmp_path)          # directory was never created
    assert backups.existing(c) == []
    assert backups.is_due(c) is True
