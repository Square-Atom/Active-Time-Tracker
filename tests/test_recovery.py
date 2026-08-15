"""Recovering automatically from a damaged database.

Written after a real incident: `data.db` was replaced by a copy of a backup
while its `-wal` sidecar was left behind, so SQLite blended two unrelated
databases. The result didn't fail — it returned *different rows on different
queries*, which is far harder to notice than an outright error.
"""

import os
import shutil
import sqlite3

import backups
import config
import pytest
import storage as storage_mod
from storage import Storage


def _cfg(tmp_path, **kw):
    c = config.Config(backup_dir=str(tmp_path / "bk"), **kw)
    c.save = lambda: None  # type: ignore[method-assign]
    return c


def _populate(path, days, seconds=3600):
    s = Storage(path)
    for day in days:
        s.add_seconds(day, "code.exe", "VS Code", "a.py", seconds)
    s.close()


def _corrupt(path):
    """Scribble over the middle of the file, past the header."""
    size = os.path.getsize(path)
    with open(path, "r+b") as fh:
        fh.seek(size // 2)
        fh.write(b"\x00" * 2048)


# --- detection -------------------------------------------------------------

def test_a_sound_database_reports_no_problem(tmp_path):
    path = str(tmp_path / "data.db")
    _populate(path, ["2026-01-01"])
    assert storage_mod.integrity_problem(path) is None


def test_a_damaged_database_is_detected(tmp_path):
    path = str(tmp_path / "data.db")
    _populate(path, [f"2026-01-{d:02d}" for d in range(1, 20)])
    _corrupt(path)
    assert storage_mod.integrity_problem(path) is not None


def test_a_missing_database_is_not_damage(tmp_path):
    assert storage_mod.integrity_problem(str(tmp_path / "nope.db")) is None


def test_a_non_database_is_reported_not_raised(tmp_path):
    path = tmp_path / "junk.db"
    path.write_bytes(b"this is not a database")
    assert storage_mod.integrity_problem(str(path)) is not None


# --- recovery --------------------------------------------------------------

def test_nothing_happens_when_the_database_is_sound(tmp_path):
    db = str(tmp_path / "data.db")
    _populate(db, ["2026-01-01"])
    cfg = _cfg(tmp_path)
    assert backups.repair_if_corrupt(cfg, db) is None


def test_a_damaged_database_is_replaced_by_the_newest_sound_backup(tmp_path):
    db = str(tmp_path / "data.db")
    _populate(db, [f"2026-01-{d:02d}" for d in range(1, 20)])

    cfg = _cfg(tmp_path)
    good = Storage(db)
    backups.run(good, cfg, today="2026-01-19")
    good.close()

    _corrupt(db)
    assert storage_mod.integrity_problem(db) is not None

    note = backups.repair_if_corrupt(cfg, db)
    assert note and "2026-01-19" in note
    assert storage_mod.integrity_problem(db) is None, "should now be sound"


def test_the_damaged_files_are_kept_not_deleted(tmp_path):
    """They may hold the newest work — never throw a user's data away."""
    db = str(tmp_path / "data.db")
    _populate(db, [f"2026-01-{d:02d}" for d in range(1, 20)])
    cfg = _cfg(tmp_path)
    s = Storage(db)
    backups.run(s, cfg, today="2026-01-19")
    s.close()
    _corrupt(db)

    backups.repair_if_corrupt(cfg, db)
    kept = [d for d in os.listdir(tmp_path) if d.startswith("damaged-")]
    assert len(kept) == 1
    assert "data.db" in os.listdir(tmp_path / kept[0])


def test_no_sidecar_is_left_beside_the_restored_database(tmp_path):
    """Leaving a -wal behind is what caused the damage in the first place, so
    the restored database must start with none.

    (The integrity check opens the database, which is how a blended WAL is
    detected at all, and SQLite may consume the sidecars in the process — so
    what matters is that none survive next to the fresh copy.)
    """
    db = str(tmp_path / "data.db")
    _populate(db, [f"2026-01-{d:02d}" for d in range(1, 20)])
    cfg = _cfg(tmp_path)
    s = Storage(db)
    backups.run(s, cfg, today="2026-01-19")
    s.close()
    _corrupt(db)
    open(db + "-wal", "wb").write(b"stale wal")
    open(db + "-shm", "wb").write(b"stale shm")

    backups.repair_if_corrupt(cfg, db)
    assert not os.path.exists(db + "-wal"), "a stale sidecar must not survive"
    assert not os.path.exists(db + "-shm")
    kept = [d for d in os.listdir(tmp_path) if d.startswith("damaged-")][0]
    assert "data.db" in os.listdir(tmp_path / kept), "the damaged copy is kept"
    assert storage_mod.integrity_problem(db) is None


def test_a_damaged_backup_is_skipped_for_an_older_sound_one(tmp_path):
    db = str(tmp_path / "data.db")
    _populate(db, [f"2026-01-{d:02d}" for d in range(1, 20)])
    cfg = _cfg(tmp_path)
    s = Storage(db)
    backups.run(s, cfg, today="2026-01-18")      # older, sound
    backups.run(s, cfg, today="2026-01-19")      # newer, will be damaged
    s.close()
    _corrupt(backups._db_path(cfg, "2026-01-19"))
    _corrupt(db)

    note = backups.repair_if_corrupt(cfg, db)
    assert note and "2026-01-18" in note, "should fall back to the sound one"
    assert storage_mod.integrity_problem(db) is None


def test_without_any_sound_backup_the_data_is_left_alone(tmp_path):
    """A damaged database still beats no database."""
    db = str(tmp_path / "data.db")
    _populate(db, [f"2026-01-{d:02d}" for d in range(1, 20)])
    _corrupt(db)
    cfg = _cfg(tmp_path)

    note = backups.repair_if_corrupt(cfg, db)
    assert note and "no healthy backup" in note
    assert os.path.exists(db), "must not delete the only copy there is"


def test_recovered_database_is_usable(tmp_path):
    db = str(tmp_path / "data.db")
    _populate(db, [f"2026-01-{d:02d}" for d in range(1, 20)])
    cfg = _cfg(tmp_path)
    s = Storage(db)
    backups.run(s, cfg, today="2026-01-19")
    s.close()
    _corrupt(db)
    backups.repair_if_corrupt(cfg, db)

    reopened = Storage(db)
    reopened.add_seconds("2026-02-01", "a.exe", "A", "", 5)
    reopened.flush()
    assert reopened.grand_total("2026-01-01", "2026-02-28") > 0
    reopened.close()
