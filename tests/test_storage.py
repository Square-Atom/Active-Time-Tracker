"""Buffered writes and read-time aggregation (merges, ignores, ranges)."""

import sqlite3

import config


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


def test_merges_fold_at_read_time_without_touching_raw_rows(store, today):
    store.add_seconds(today, "godot.exe", "Godot", "main.tscn", 100)
    store.add_seconds(today, "godot_console.exe", "Godot", "", 50)
    store.add_seconds(today, "chrome.exe", "Chrome", "", 200)
    cfg = config.Config(merges=[
        {"name": "Godot", "members": ["godot.exe", "godot_console.exe"]}])

    merged = {a["app"]: a["seconds"] for a in
              store.totals_by_app(today, today, cfg.merge_map())}
    assert merged["merge::Godot"] == 150
    assert merged["chrome.exe"] == 200

    # the underlying per-exe rows survive, so merging stays reversible
    raw = {a["app"] for a in store.totals_by_app(today, today)}
    assert {"godot.exe", "godot_console.exe"} <= raw


def test_group_file_breakdown_spans_members(store, today):
    store.add_seconds(today, "godot.exe", "Godot", "main.tscn", 100)
    store.add_seconds(today, "godot_console.exe", "Godot", "main.tscn", 20)
    files = store.totals_by_file(today, today, ["godot.exe", "godot_console.exe"])
    assert {f["file"]: f["seconds"] for f in files} == {"main.tscn": 120}


def test_ignored_apps_are_excluded(store, today):
    store.add_seconds(today, "game.exe", "Game", "", 900)
    store.add_seconds(today, "code.exe", "VS Code", "", 100)
    apps = store.totals_by_app(today, today, None, {"game.exe"})
    assert [a["app"] for a in apps] == ["code.exe"]


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


def test_backup_is_a_standalone_file(store, tmp_path, today):
    store.add_seconds(today, "a.exe", "A", "", 1)
    dest = tmp_path / "copy.db"
    store.backup_to(str(dest))
    assert dest.exists() and dest.stat().st_size > 0
    # no sidecars needed to read it
    assert not (tmp_path / "copy.db-wal").exists()
