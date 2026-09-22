"""Buffered writes and read-time aggregation (tags, ignores, ranges)."""

import os
import sqlite3

import config
import pytest
import storage


def test_buffered_writes_accumulate(store, today):
    store.add_seconds(today, "code.exe", "VS Code", "main.py", 120)
    store.add_seconds(today, "code.exe", "VS Code", "main.py", 60)
    store.add_seconds(today, "code.exe", "VS Code", "test.py", 30)
    apps = store.totals_by_app(today, today)
    assert apps[0]["seconds"] == 210
    files = {f["file"]: f["seconds"] for f in store.totals_by_file(today, today, "code.exe")}
    assert files == {"main.py": 180, "test.py": 30}


def test_unflushed_time_is_still_reported(store, today):
    """Reads must include buffered-but-unwritten seconds, or the dashboard
    would appear to stall between flushes."""
    store.add_seconds(today, "a.exe", "A", "", 5)
    assert store.totals_by_app(today, today)[0]["seconds"] == 5


def test_range_filtering(store):
    store.add_seconds("2026-01-05", "a.exe", "A", "", 100)
    store.add_seconds("2026-02-05", "a.exe", "A", "", 50)
    store.flush()
    assert store.grand_total("2026-01-01", "2026-01-31") == 100
    assert store.grand_total("2026-01-01", "2026-12-31") == 150
    assert store.totals_by_day("2026-01-01", "2026-12-31") == {
        "2026-01-05": 100, "2026-02-05": 50}


def test_tags_fold_at_read_time_without_touching_raw_rows(store, today):
    store.add_seconds(today, "code.exe", "VS Code", "main.py", 100)
    store.add_seconds(today, "chrome.exe", "Chrome", "GitHub", 50)
    store.add_seconds(today, "chrome.exe", "Chrome", "YouTube", 200)
    cfg = config.Config()
    cfg.set_item_tag("Work", "code.exe", None, True)
    cfg.set_item_tag("Work", "chrome.exe", "GitHub", True)

    totals = {t["name"]: t["seconds"] for t in
              store.totals_by_tag(today, today, cfg.tags)}
    assert totals == {"Work": 150}, "YouTube belongs to no tag, so it isn't listed"

    # the underlying per-app rows survive, so tagging stays reversible
    raw = {a["app"]: a["seconds"] for a in store.totals_by_app(today, today)}
    assert raw == {"code.exe": 100, "chrome.exe": 250}


def test_an_item_in_two_tags_counts_toward_both(store, today):
    store.add_seconds(today, "code.exe", "VS Code", "main.py", 100)
    cfg = config.Config()
    cfg.set_item_tag("Work", "code.exe", "main.py", True)
    cfg.set_item_tag("Python", "code.exe", "main.py", True)
    totals = {t["name"]: t["seconds"] for t in
              store.totals_by_tag(today, today, cfg.tags)}
    assert totals == {"Work": 100, "Python": 100}


def test_a_tagged_app_counts_its_files_once_even_if_they_are_tagged_too(
        store, today):
    """Tag totals overlap each other, but never double inside one tag."""
    store.add_seconds(today, "code.exe", "VS Code", "main.py", 100)
    store.add_seconds(today, "code.exe", "VS Code", "test.py", 20)
    cfg = config.Config()
    cfg.set_item_tag("Work", "code.exe", None, True)
    cfg.set_item_tag("Work", "code.exe", "main.py", True)
    tag = store.totals_by_tag(today, today, cfg.tags)[0]
    assert tag["seconds"] == 120
    assert [(i["file"], i["seconds"]) for i in tag["items"]] == [(None, 120)]


def test_a_tag_with_no_time_in_the_range_is_left_out(store, today):
    """A tag you didn't touch has nothing to say about the range."""
    store.add_seconds(today, "code.exe", "VS Code", "", 100)
    store.add_seconds("2020-01-01", "game.exe", "Game", "", 500)
    cfg = config.Config()
    cfg.create_tag("Someday")                       # nothing in it at all
    cfg.set_item_tag("Old", "game.exe", None, True)  # nothing in *this* range
    cfg.set_item_tag("Now", "code.exe", None, True)
    assert [t["name"] for t in store.totals_by_tag(today, today, cfg.tags)] == ["Now"]
    assert [t["name"] for t in
            store.totals_by_tag("2020-01-01", today, cfg.tags)] == ["Old", "Now"]


def test_totals_by_app_file_splits_app_level_time_from_files(store, today):
    store.add_seconds(today, "code.exe", "VS Code", "", 30)
    store.add_seconds(today, "code.exe", "VS Code", "main.py", 100)
    rows = {(r["app"], r["file"]): r["seconds"]
            for r in store.totals_by_app_file(today, today)}
    assert rows == {("code.exe", ""): 30, ("code.exe", "main.py"): 100}


def test_ignored_apps_are_excluded(store, today):
    store.add_seconds(today, "game.exe", "Game", "", 900)
    store.add_seconds(today, "code.exe", "VS Code", "", 100)
    apps = store.totals_by_app(today, today, {"game.exe"})
    assert [a["app"] for a in apps] == ["code.exe"]
    assert [r["app"] for r in
            store.totals_by_app_file(today, today, {"game.exe"})] == ["code.exe"]


def test_known_apps_is_busiest_first(store, today):
    store.add_seconds(today, "a.exe", "A", "", 10)
    store.add_seconds(today, "b.exe", "B", "", 99)
    assert [e for e, _ in store.known_apps()] == ["b.exe", "a.exe"]


def test_backup_captures_data_still_in_the_wal(store, tmp_path, today):
    """A filesystem copy of data.db would miss recent commits in WAL mode;
    the backup API must not."""
    store.add_seconds(today, "code.exe", "VS Code", "main.py", 42)
    dest = tmp_path / "copy.db"
    store.backup_to(str(dest))

    conn = sqlite3.connect(dest)
    try:
        total = conn.execute("SELECT SUM(seconds) FROM activity").fetchone()[0]
    finally:
        conn.close()
    assert total == 42


def _make_backup(store, tmp_path, name="bk.db"):
    dest = tmp_path / name
    store.backup_to(str(dest))
    return str(dest)


def test_describe_backup_summarises_a_real_backup(store, tmp_path):
    store.add_seconds("2026-01-01", "code.exe", "VS Code", "a.py", 60)
    store.add_seconds("2026-01-03", "chrome.exe", "Chrome", "", 30)
    info = storage.describe_backup(_make_backup(store, tmp_path))
    assert info["rows"] == 2
    assert info["days"] == 2
    assert info["apps"] == 2
    assert (info["first_day"], info["last_day"]) == ("2026-01-01", "2026-01-03")
    assert info["seconds"] == 90


@pytest.mark.parametrize("content,missing", [
    (b"not a database at all", False),
    (None, True),                        # file doesn't exist
])
def test_describe_backup_rejects_junk(tmp_path, content, missing):
    path = tmp_path / "junk.db"
    if not missing:
        path.write_bytes(content)
    with pytest.raises(storage.BadBackup):
        storage.describe_backup(str(path))


def test_describe_backup_rejects_a_database_without_our_table(tmp_path):
    path = tmp_path / "other.db"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE something_else (x INTEGER)")
    conn.commit(); conn.close()
    with pytest.raises(storage.BadBackup):
        storage.describe_backup(str(path))


def test_describe_backup_does_not_modify_the_file(store, tmp_path):
    store.add_seconds("2026-01-01", "a.exe", "A", "", 5)
    path = _make_backup(store, tmp_path)
    before = os.path.getmtime(path), os.path.getsize(path)
    storage.describe_backup(path)
    assert (os.path.getmtime(path), os.path.getsize(path)) == before


def test_restore_replace_discards_current_data(store, tmp_path):
    store.add_seconds("2026-01-01", "code.exe", "VS Code", "old.py", 100)
    path = _make_backup(store, tmp_path)

    store.add_seconds("2026-02-02", "game.exe", "Game", "", 500)   # after the backup
    store.flush()
    assert store.grand_total("2026-01-01", "2026-12-31") == 600

    store.restore_from(path, storage.REPLACE)
    apps = {a["app"] for a in store.totals_by_app("2026-01-01", "2026-12-31")}
    assert apps == {"code.exe"}, "everything not in the backup should be gone"
    assert store.grand_total("2026-01-01", "2026-12-31") == 100


def test_restore_merge_keeps_data_missing_from_the_backup(store, tmp_path):
    store.add_seconds("2026-01-01", "code.exe", "VS Code", "old.py", 100)
    path = _make_backup(store, tmp_path)

    store.add_seconds("2026-02-02", "game.exe", "Game", "", 500)
    store.restore_from(path, storage.MERGE)
    apps = {a["app"] for a in store.totals_by_app("2026-01-01", "2026-12-31")}
    assert apps == {"code.exe", "game.exe"}
    assert store.grand_total("2026-01-01", "2026-12-31") == 600


def test_restore_merge_takes_the_larger_side_not_the_sum(store, tmp_path):
    """A backup usually overlaps the current data — adding would double-count."""
    store.add_seconds("2026-01-01", "code.exe", "VS Code", "a.py", 100)
    path = _make_backup(store, tmp_path)

    store.restore_from(path, storage.MERGE)      # merge the same data back in
    assert store.grand_total("2026-01-01", "2026-01-01") == 100, "double-counted"

    # and where the live side has more, the live value wins
    store.add_seconds("2026-01-01", "code.exe", "VS Code", "a.py", 50)
    store.restore_from(path, storage.MERGE)
    assert store.grand_total("2026-01-01", "2026-01-01") == 150


def test_restore_recovers_history_lost_from_the_live_database(store, tmp_path):
    """The case this feature exists for."""
    for day in ("2026-03-01", "2026-03-02", "2026-03-03"):
        store.add_seconds(day, "code.exe", "VS Code", "a.py", 100)
    path = _make_backup(store, tmp_path)

    store.flush()
    store._conn.execute("DELETE FROM activity")     # simulate the loss
    store._conn.commit()
    assert store.grand_total("2026-01-01", "2026-12-31") == 0

    store.restore_from(path, storage.MERGE)
    assert store.grand_total("2026-01-01", "2026-12-31") == 300


def test_restore_flushes_buffered_time_first(store, tmp_path, today):
    store.add_seconds("2026-01-01", "a.exe", "A", "", 10)
    path = _make_backup(store, tmp_path)
    store.add_seconds(today, "b.exe", "B", "", 7)     # still only in the buffer
    store.restore_from(path, storage.MERGE)
    assert store.grand_total(today, today) == 7, "buffered seconds were dropped"


def test_restore_rejects_junk_without_touching_the_data(store, tmp_path):
    store.add_seconds("2026-01-01", "a.exe", "A", "", 42)
    junk = tmp_path / "junk.db"
    junk.write_bytes(b"definitely not sqlite")
    with pytest.raises(storage.BadBackup):
        store.restore_from(str(junk))
    assert store.grand_total("2026-01-01", "2026-01-01") == 42


def test_restore_rejects_an_unknown_mode(store, tmp_path):
    store.add_seconds("2026-01-01", "a.exe", "A", "", 1)
    path = _make_backup(store, tmp_path)
    with pytest.raises(ValueError):
        store.restore_from(path, "obliterate")


def test_the_connection_still_works_after_restoring(store, tmp_path, today):
    """Rows are copied over an ATTACHed database, so the live connection --
    and the tracker writing through it -- must survive."""
    store.add_seconds("2026-01-01", "a.exe", "A", "", 10)
    path = _make_backup(store, tmp_path)
    store.restore_from(path, storage.REPLACE)

    store.add_seconds(today, "b.exe", "B", "", 5)     # keep tracking
    store.flush()
    assert store.grand_total(today, today) == 5
    store.backup_to(str(tmp_path / "after.db"))       # and still back up


def test_backup_is_a_standalone_file(store, tmp_path, today):
    store.add_seconds(today, "a.exe", "A", "", 1)
    dest = tmp_path / "copy.db"
    store.backup_to(str(dest))
    assert dest.exists() and dest.stat().st_size > 0
    # no sidecars needed to read it
    assert not (tmp_path / "copy.db-wal").exists()


# --- moving time between records ------------------------------------------

def _files(store, start, end, app="ps.exe"):
    return {f["file"]: f["seconds"]
            for f in store.totals_by_file(start, end, app)}


def test_moving_all_of_a_record_merges_it_into_the_other(store, today):
    store.add_seconds(today, "ps.exe", "Photoshop", "", 600)
    store.add_seconds(today, "ps.exe", "Photoshop", "logo.psd", 300)
    moved = store.move_time(today, today, "ps.exe", "", "logo.psd", 600)
    assert moved == 600
    assert _files(store, today, today) == {"logo.psd": 900}


def test_moving_part_of_a_record_leaves_the_rest(store, today):
    store.add_seconds(today, "ps.exe", "Photoshop", "", 600)
    store.move_time(today, today, "ps.exe", "", "logo.psd", 200)
    assert _files(store, today, today) == {"": 400, "logo.psd": 200}


def test_moving_to_a_new_name_creates_it(store, today):
    store.add_seconds(today, "ps.exe", "Photoshop", "Untitled-1", 60)
    store.move_time(today, today, "ps.exe", "Untitled-1", "logo.psd", 60)
    assert _files(store, today, today) == {"logo.psd": 60}
    assert store.totals_by_app(today, today)[0]["app_name"] == "Photoshop"


def test_moving_stays_inside_the_range_and_on_its_own_days(store):
    """A one-off correction: other days — past or future — keep their record,
    and moved time stays on the day it was spent."""
    for day in ("2026-03-01", "2026-03-02", "2026-03-03", "2026-03-04"):
        store.add_seconds(day, "ps.exe", "Photoshop", "", 100)
    moved = store.move_time("2026-03-02", "2026-03-03", "ps.exe", "",
                            "logo.psd", 150)
    assert moved == 150
    # Latest day first: all of the 3rd, then half of the 2nd.
    assert _files(store, "2026-03-03", "2026-03-03") == {"logo.psd": 100}
    assert _files(store, "2026-03-02", "2026-03-02") == {"": 50, "logo.psd": 50}
    assert _files(store, "2026-03-01", "2026-03-01") == {"": 100}
    assert _files(store, "2026-03-04", "2026-03-04") == {"": 100}


def test_moving_includes_time_not_yet_flushed(store, today):
    store.add_seconds(today, "ps.exe", "Photoshop", "", 30)   # still buffered
    assert store.move_time(today, today, "ps.exe", "", "a.psd", 30) == 30
    assert _files(store, today, today) == {"a.psd": 30}


def test_moving_leaves_other_apps_alone(store, today):
    store.add_seconds(today, "ps.exe", "Photoshop", "", 60)
    store.add_seconds(today, "code.exe", "VS Code", "", 60)
    store.move_time(today, today, "ps.exe", "", "a.psd", 60)
    assert _files(store, today, today, "code.exe") == {"": 60}


def test_moving_a_record_onto_itself_does_nothing(store, today):
    store.add_seconds(today, "ps.exe", "Photoshop", "a.psd", 60)
    assert store.move_time(today, today, "ps.exe", "a.psd", "a.psd", 60) == 0
    assert _files(store, today, today) == {"a.psd": 60}


def test_known_files_are_most_recent_first(store):
    store.add_seconds("2026-03-01", "ps.exe", "Photoshop", "old.psd", 900)
    store.add_seconds("2026-03-05", "ps.exe", "Photoshop", "new.psd", 10)
    store.add_seconds("2026-03-05", "ps.exe", "Photoshop", "", 10)
    assert store.known_files("ps.exe") == ["new.psd", "old.psd"]
