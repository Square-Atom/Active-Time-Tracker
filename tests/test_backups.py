"""Daily rotating backups: location, rotation, scheduling, and failure safety."""

import os

import backups
import config
import storage


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


def test_todays_backup_is_refreshed_through_the_day(store, tmp_path, today):
    """Backing up once a day left everything since the morning unprotected."""
    c = _cfg(tmp_path, backup_interval_hours=1)
    backups.run(store, c, today=today)
    assert backups.is_due(c, today) is False        # just written

    later = os.path.getmtime(backups._db_path(c, today)) + 3601
    assert backups.is_due(c, today, now=later) is True, "should refresh hourly"


def test_interval_is_respected(store, tmp_path, today):
    c = _cfg(tmp_path, backup_interval_hours=6)
    backups.run(store, c, today=today)
    written = os.path.getmtime(backups._db_path(c, today))
    assert backups.is_due(c, today, now=written + 3600) is False   # 1h later
    assert backups.is_due(c, today, now=written + 6 * 3600) is True


def test_zero_interval_means_every_check(store, tmp_path, today):
    c = _cfg(tmp_path, backup_interval_hours=0)
    backups.run(store, c, today=today)
    assert backups.is_due(c, today) is True


# --- refusing to overwrite a good backup with a worse one ------------------

def test_a_shrunken_backup_does_not_replace_a_good_one(store, tmp_path, today):
    """The incident this guards against: the live database was reverted, and a
    later backup would have baked that in and destroyed the last good copy."""
    for day in ("2026-08-12", "2026-08-13", "2026-08-14"):
        store.add_seconds(day, "code.exe", "VS Code", "a.py", 3600)
    c = _cfg(tmp_path)
    good = backups.run(store, c, today=today)
    before = storage.describe_backup(good)
    assert before["seconds"] == 3 * 3600

    # simulate the loss, then let the next scheduled backup run
    store.flush()
    store._conn.execute("DELETE FROM activity WHERE day != '2026-08-12'")
    store._conn.commit()
    assert backups.run(store, c, today=today) is None, "should refuse"

    after = storage.describe_backup(backups._db_path(c, today))
    assert after["seconds"] == before["seconds"], "the good copy must survive"


def test_no_part_file_is_left_after_a_refusal(store, tmp_path, today):
    c = _cfg(tmp_path)
    store.add_seconds("2026-08-12", "a.exe", "A", "", 100)
    backups.run(store, c, today=today)
    store.flush()
    store._conn.execute("DELETE FROM activity")
    store._conn.commit()
    backups.run(store, c, today=today)
    assert [n for n in os.listdir(backups.backup_dir(c)) if n.endswith(".part")] == []


def test_growing_data_still_replaces_normally(store, tmp_path, today):
    c = _cfg(tmp_path)
    store.add_seconds("2026-08-12", "a.exe", "A", "", 100)
    backups.run(store, c, today=today)
    store.add_seconds("2026-08-12", "a.exe", "A", "", 500)
    assert backups.run(store, c, today=today) is not None
    assert storage.describe_backup(backups._db_path(c, today))["seconds"] == 600


def test_force_overrides_the_guard(store, tmp_path, today):
    """The manual button means "save what I have now", whatever that is."""
    c = _cfg(tmp_path)
    store.add_seconds("2026-08-12", "a.exe", "A", "", 500)
    backups.run(store, c, today=today)
    store.flush()
    store._conn.execute("DELETE FROM activity")
    store._conn.commit()

    assert backups.run(store, c, today=today, force=True) is not None
    assert storage.describe_backup(backups._db_path(c, today))["seconds"] == 0


def test_the_guard_only_applies_to_the_same_day(store, tmp_path):
    """A new day starts its own file, so yesterday is never compared against."""
    c = _cfg(tmp_path)
    store.add_seconds("2026-08-12", "a.exe", "A", "", 5000)
    backups.run(store, c, today="2026-08-12")
    store.flush()
    store._conn.execute("DELETE FROM activity")
    store._conn.commit()
    assert backups.run(store, c, today="2026-08-13") is not None


# --- backing up as the app closes -----------------------------------------

def test_exit_backup_runs_even_when_one_is_not_due(store, tmp_path, today):
    """Quitting is exactly when the newest work is at risk; waiting for the
    next interval would lose everything since the last hourly run."""
    c = _cfg(tmp_path, backup_interval_hours=24)
    backups.run(store, c, today=today)
    assert backups.is_due(c, today) is False        # nowhere near due

    store.add_seconds(today, "code.exe", "VS Code", "late.py", 900)
    assert backups.run_on_exit(store, c) is not None
    assert storage.describe_backup(backups._db_path(c, today))["seconds"] == 900


def test_exit_backup_captures_time_still_in_the_buffer(store, tmp_path, today):
    c = _cfg(tmp_path)
    store.add_seconds(today, "code.exe", "VS Code", "a.py", 45)   # unflushed
    backups.run_on_exit(store, c)
    assert storage.describe_backup(backups._db_path(c, today))["seconds"] == 45


def test_exit_backup_respects_the_setting(store, tmp_path, today):
    c = _cfg(tmp_path, backup_enabled=False)
    store.add_seconds(today, "a.exe", "A", "", 10)
    assert backups.run_on_exit(store, c) is None
    assert not os.path.exists(backups._db_path(c, today))


def test_exit_backup_cannot_overwrite_a_good_copy(store, tmp_path, today):
    """Quitting after something damaged the database must not bake it in."""
    store.add_seconds("2026-08-12", "a.exe", "A", "", 4000)
    c = _cfg(tmp_path)
    backups.run(store, c, today=today)
    store.flush()
    store._conn.execute("DELETE FROM activity")
    store._conn.commit()

    assert backups.run_on_exit(store, c) is None
    assert storage.describe_backup(backups._db_path(c, today))["seconds"] == 4000


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


def test_list_backups_is_newest_first_with_paths(store, tmp_path):
    c = _cfg(tmp_path)
    for day in ("2026-01-01", "2026-01-03", "2026-01-02"):
        backups.run(store, c, today=day)
    listed = backups.list_backups(c)
    assert [d for d, _ in listed] == ["2026-01-03", "2026-01-02", "2026-01-01"]
    assert all(os.path.exists(p) for _, p in listed)


def test_safety_copy_is_named_apart_from_the_dated_backups(store, tmp_path, today):
    """It must not displace today's backup or vanish in rotation — it's the
    undo for a mistaken restore."""
    store.add_seconds(today, "a.exe", "A", "", 5)
    c = _cfg(tmp_path, backup_keep=1)
    backups.run(store, c, today=today)

    snap = backups.safety_copy(store, c)
    assert snap and os.path.exists(snap)
    assert "pre-restore" in os.path.basename(snap)

    # rotation still only prunes the dated ones, leaving the snapshot alone
    backups.run(store, c, today="2099-01-01")
    assert os.path.exists(snap)
    assert backups.existing(c) == ["2099-01-01"]


def test_safety_copy_can_be_restored_from(store, tmp_path, today):
    import storage as storage_mod
    store.add_seconds(today, "a.exe", "A", "", 5)
    c = _cfg(tmp_path)
    snap = backups.safety_copy(store, c)
    assert storage_mod.describe_backup(snap)["seconds"] == 5


def test_safety_copy_failure_is_swallowed(store, tmp_path, monkeypatch):
    c = _cfg(tmp_path)
    monkeypatch.setattr(store, "backup_to",
                        lambda p: (_ for _ in ()).throw(OSError("nope")))
    assert backups.safety_copy(store, c) is None


def test_unreadable_backup_dir_reports_nothing(tmp_path):
    c = _cfg(tmp_path)          # directory was never created
    assert backups.existing(c) == []
    assert backups.is_due(c) is True
