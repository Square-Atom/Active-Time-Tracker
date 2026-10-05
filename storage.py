"""SQLite storage for focus time.

We aggregate at the (day, app, file) grain. Every active second increments the
`seconds` counter for the matching row. Writes are buffered in memory and
flushed periodically (and on pause/quit) so we're not committing every second.
"""

from __future__ import annotations

import datetime as dt
import os
import sqlite3
import threading
from collections import defaultdict

import config

# Timeline states. `untracked` is focus we deliberately don't name (an ignored
# app, or no window at all), drawn like idle rather than as a gap.
ACTIVE = "active"
IDLE = "idle"
UNTRACKED = "untracked"

# Ticks closer together than this join into one continuous block. A wider gap
# is a hole in the record (app closed, paused, asleep) and stays empty.
SEGMENT_JOIN_SECONDS = 1.0

NOTE_TS_FORMAT = "%Y-%m-%d %H:%M:%S"   # notes are keyed by local date + time

REPLACE = "replace"   # discard current data, use the backup's
MERGE = "merge"       # keep whichever side recorded more per (day, app, file)


class BadBackup(Exception):
    """The chosen file isn't a database this app can read."""


def describe_backup(path: str) -> dict:
    """Summarise a backup so the user can confirm before overwriting anything.

    Opens read-only, so inspecting a file can never modify it.
    """
    if not os.path.isfile(path):
        raise BadBackup("That file doesn't exist.")
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    except sqlite3.Error as exc:
        raise BadBackup(f"Couldn't open the file: {exc}") from exc
    try:
        table = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='activity'"
        ).fetchone()
        if not table:
            raise BadBackup("This doesn't look like an Active Time Tracker backup.")
        rows, days, first, last, seconds = conn.execute(
            "SELECT COUNT(*), COUNT(DISTINCT day), MIN(day), MAX(day),"
            " COALESCE(SUM(seconds), 0) FROM activity"
        ).fetchone()
        apps = conn.execute(
            "SELECT COUNT(DISTINCT app) FROM activity").fetchone()[0]
    except sqlite3.DatabaseError as exc:
        raise BadBackup(f"The file is not a readable database: {exc}") from exc
    finally:
        conn.close()
    return {"rows": rows, "days": days, "apps": apps,
            "first_day": first, "last_day": last, "seconds": seconds}


def integrity_problem(path: str) -> str | None:
    """None if the database is sound, else SQLite's description of the damage.

    Worth running before anything opens the database for real: a `data.db`
    replaced by hand while its `-wal` sidecar was left behind blends two
    unrelated databases, and the result reads *differently on each query*
    rather than failing outright.
    """
    if not os.path.isfile(path):
        return None                       # nothing there yet is not damage
    try:
        conn = sqlite3.connect(path)
    except sqlite3.Error as exc:
        return str(exc)
    try:
        result = conn.execute("PRAGMA integrity_check").fetchone()[0]
    except sqlite3.DatabaseError as exc:
        return str(exc)
    finally:
        conn.close()
    return None if result == "ok" else result


def item_label(app_name: str, file: str | None) -> str:
    """How a tagged item reads in the chart: the app, or a file inside it."""
    if file is None:
        return app_name
    return f"{file or '(no file)'}  ·  {app_name}"


def _fold(rows, tags) -> tuple[list[dict], dict[str, float]]:
    """Fold (app, file) totals into one row per tag, busiest first.

    `rows` are `totals_by_app_file` results; `tags` is `config.Config.tags`.
    An item is either a whole app (no `file`) or one file/site inside it, and
    a row counts toward *every* tag that claims it — so tag totals overlap by
    design and don't add up to the grand total. Within a single tag a row is
    counted once, even when both the app and the file are in that same tag.

    Only tags with time in this range come back: a tag you didn't touch has
    nothing to say about the range, and untagged time isn't reported here at
    all — that's what the Apps view shows.

    Also returns seconds per group name. A group counts each row once however
    many of its tags claim it, for the same reason a tag does: it's time
    spent, not a tally.
    """
    folded = []
    group_seconds: dict[str, float] = defaultdict(float)
    for tag in tags:
        name = tag.get("name", "")
        apps, files = set(), set()
        for entry in tag.get("items", []):
            app, file = config.item_key(entry.get("app", ""), entry.get("file"))
            (apps if file is None else files).add(app if file is None else (app, file))
        folded.append({"key": config.tag_key(name), "name": name,
                       "group": tag.get("group", ""),
                       "seconds": 0.0, "apps": apps, "files": files,
                       "parts": defaultdict(float), "names": {}})

    for row in rows:
        app, file, seconds = row["app"], row["file"], row["seconds"]
        groups = set()
        for tag in folded:
            if app in tag["apps"]:
                part = (app, None)          # the whole app covers this row
            elif (app, file) in tag["files"]:
                part = (app, file)
            else:
                continue
            tag["seconds"] += seconds
            tag["parts"][part] += seconds
            tag["names"][app] = row["app_name"]
            if tag["group"]:
                groups.add(tag["group"])
        for group in groups:
            group_seconds[group] += seconds

    out = []
    for tag in folded:
        if not tag["seconds"]:
            continue
        items = []
        for (app, file), seconds in tag["parts"].items():
            app_name = tag["names"].get(app) or config.friendly_name(app)
            items.append({"app": app, "file": file, "app_name": app_name,
                          "label": item_label(app_name, file), "seconds": seconds,
                          "key": f"{tag['key']}\x00{app}\x00{'' if file is None else file}"})
        items.sort(key=lambda i: i["seconds"], reverse=True)
        out.append({"key": tag["key"], "name": tag["name"], "tag": tag["name"],
                    "group": tag["group"],
                    "seconds": tag["seconds"], "items": items})
    out.sort(key=lambda t: t["seconds"], reverse=True)
    return out, group_seconds


def fold_tags(rows, tags) -> list[dict]:
    """One row per tag with time in `rows` (see `_fold`), groups set aside."""
    return _fold(rows, tags)[0]


def fold_groups(rows, tags, groups) -> list[dict]:
    """`fold_tags`, with grouped tags gathered under a row for their group.

    Ungrouped tags come back as `fold_tags` gives them; a group is
    `{key, name, group, seconds, tags}` holding its tags busiest first, and
    sorts among the loose tags by its own total. That total counts a row once
    even when several of the group's tags claim it, so it can be less than
    the tags under it add up to. A group with no time in the range is left
    out, like a tag.
    """
    folded, seconds = _fold(rows, tags)
    known = set(groups or [])
    members: dict[str, list[dict]] = defaultdict(list)
    out = []
    for tag in folded:
        if tag["group"] in known:
            members[tag["group"]].append(tag)
        else:
            out.append(tag)
    for name, inside in members.items():
        out.append({"key": config.group_key(name), "name": name, "group": name,
                    "seconds": seconds[name], "tags": inside})
    out.sort(key=lambda t: t["seconds"], reverse=True)
    return out


class Storage:
    def __init__(self, db_path: str = config.DB_PATH):
        self.db_path = db_path
        self._lock = threading.Lock()
        # (day, app, app_name, file) -> accumulated seconds not yet written
        self._buffer: dict[tuple[str, str, str, str], float] = defaultdict(float)
        # The timeline block being extended tick by tick, plus finished blocks
        # not yet written. `id` is its row once the open block has been saved.
        self._segment: dict | None = None
        self._closed_segments: list[dict] = []
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        # Keep the -wal sidecar from growing without bound. A large stale WAL
        # is what makes a hand-replaced data.db so damaging.
        self._conn.execute("PRAGMA journal_size_limit=4194304")
        self._init_schema()

    def _init_schema(self) -> None:
        with self._conn:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS activity (
                    day      TEXT    NOT NULL,
                    app      TEXT    NOT NULL,
                    app_name TEXT    NOT NULL,
                    file     TEXT    NOT NULL DEFAULT '',
                    seconds  REAL    NOT NULL DEFAULT 0,
                    PRIMARY KEY (day, app, file)
                )
                """
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_activity_day ON activity(day)"
            )
            # One row per uninterrupted block of the same focus, in epoch
            # seconds. `day` is the local day the block belongs to.
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS timeline (
                    day      TEXT NOT NULL,
                    start    REAL NOT NULL,
                    end      REAL NOT NULL,
                    state    TEXT NOT NULL,
                    app      TEXT NOT NULL DEFAULT '',
                    app_name TEXT NOT NULL DEFAULT ''
                )
                """
            )
            self._conn.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_timeline_block"
                " ON timeline(start, state, app)"
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_timeline_day ON timeline(day)"
            )
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS notes (
                    ts   TEXT PRIMARY KEY,
                    text TEXT NOT NULL
                )
                """
            )

    # -- writing ----------------------------------------------------------

    def add_seconds(self, day: str, app: str, app_name: str, file: str, seconds: float) -> None:
        """Buffer active time for a (day, app, file)."""
        with self._lock:
            self._buffer[(day, app, app_name, file)] += seconds

    def add_span(self, state: str, start: float, end: float,
                 app: str = "", app_name: str = "") -> None:
        """Record that [start, end] (epoch seconds) was spent in `state`.

        Contiguous spans with the same focus grow one block rather than adding
        a row per tick. A block never crosses local midnight, so each day's
        timeline stands on its own.
        """
        if end <= start:
            return
        with self._lock:
            while True:
                piece_end = min(end, _next_midnight(start))
                self._extend_segment(state, start, piece_end, app, app_name)
                if piece_end >= end:
                    break
                start = piece_end

    def _extend_segment(self, state, start, end, app, app_name) -> None:
        seg = self._segment
        if (seg and seg["state"] == state and seg["app"] == app
                and seg["day"] == _local_day(start)
                and abs(start - seg["end"]) <= SEGMENT_JOIN_SECONDS):
            seg["end"] = max(seg["end"], end)
            seg["app_name"] = app_name
            return
        if seg:
            self._closed_segments.append(seg)
        self._segment = {"id": None, "day": _local_day(start), "start": start,
                         "end": end, "state": state, "app": app,
                         "app_name": app_name}

    def _write_segments(self, segments) -> None:
        for seg in segments:
            if seg["id"] is None:
                self._conn.execute(
                    """
                    INSERT INTO timeline (day, start, end, state, app, app_name)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(start, state, app) DO UPDATE SET
                        end = MAX(timeline.end, excluded.end)
                    """,
                    (seg["day"], seg["start"], seg["end"], seg["state"],
                     seg["app"], seg["app_name"]),
                )
                # lastrowid isn't reliable after an upsert that updated.
                seg["id"] = self._conn.execute(
                    "SELECT rowid FROM timeline WHERE start = ? AND state = ?"
                    " AND app = ?", (seg["start"], seg["state"], seg["app"]),
                ).fetchone()[0]
            else:
                self._conn.execute(
                    "UPDATE timeline SET end = MAX(end, ?), app_name = ?"
                    " WHERE rowid = ?",
                    (seg["end"], seg["app_name"], seg["id"]),
                )

    def _write(self, items, segments=()) -> None:
        """Persist buffered (key, seconds) pairs and timeline blocks together."""
        with self._conn:
            self._write_segments(segments)
            for (day, app, app_name, file), seconds in items:
                self._conn.execute(
                    """
                    INSERT INTO activity (day, app, app_name, file, seconds)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(day, app, file) DO UPDATE SET
                        seconds = seconds + excluded.seconds,
                        app_name = excluded.app_name
                    """,
                    (day, app, app_name, file, seconds),
                )

    def flush(self) -> None:
        with self._lock:
            if not (self._buffer or self._closed_segments or self._segment):
                return
            items = list(self._buffer.items())
            self._buffer.clear()
            segments = self._closed_segments
            self._closed_segments = []
            if self._segment:
                # The open block is written too, then updated in place, so a
                # crash loses at most one flush interval of it.
                segments.append(self._segment)
            # Written under the lock: this assigns the open block its row id,
            # and a concurrent flush must not insert it a second time.
            self._write(items, segments)

    def close(self) -> None:
        self.flush()
        self._conn.close()

    def move_time(self, start: str, end: str, app: str, src: str, dst: str,
                  seconds: float) -> float:
        """Re-file up to `seconds` of one app's `src` record as `dst`, within
        [start, end]. Returns how much actually moved.

        This is a one-off correction of what's already recorded — typically
        "(no file)" time from before a document was first saved — so it
        touches only the days in the range and sets up no rule for the
        future. Time lands on the same day it came from, merging into `dst`
        where that already has a row. The latest days are taken first.
        """
        if src == dst or seconds <= 0:
            return 0.0
        self.flush()
        moved = 0.0
        with self._lock, self._conn:
            rows = self._conn.execute(
                "SELECT day, app_name, seconds FROM activity"
                " WHERE app = ? AND file = ? AND day BETWEEN ? AND ?"
                " ORDER BY day DESC",
                (app, src, start, end),
            ).fetchall()
            for day, app_name, have in rows:
                take = min(have, seconds - moved)
                if take <= 0:
                    break
                if have - take < 0.5:       # don't leave a sliver behind
                    take = have
                    self._conn.execute(
                        "DELETE FROM activity WHERE day = ? AND app = ? AND file = ?",
                        (day, app, src))
                else:
                    self._conn.execute(
                        "UPDATE activity SET seconds = seconds - ?"
                        " WHERE day = ? AND app = ? AND file = ?",
                        (take, day, app, src))
                self._conn.execute(
                    """
                    INSERT INTO activity (day, app, app_name, file, seconds)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(day, app, file) DO UPDATE SET
                        seconds = seconds + excluded.seconds
                    """,
                    (day, app, app_name, dst, take),
                )
                moved += take
        return moved

    def known_files(self, app: str) -> list[str]:
        """Every file name ever recorded for `app`, most recently used first."""
        self.flush()
        cur = self._conn.execute(
            "SELECT file FROM activity WHERE app = ? AND file != ''"
            " GROUP BY file ORDER BY MAX(day) DESC, SUM(seconds) DESC",
            (app,),
        )
        return [r[0] for r in cur]

    def restore_from(self, path: str, mode: str = REPLACE) -> int:
        """Load activity from a backup file. Returns the resulting row count.

        Rows are copied with SQL against an ATTACHed database rather than by
        swapping files, so the live connection — and the tracker writing
        through it — keep working throughout.

        `REPLACE` discards what's here; `MERGE` keeps whichever side recorded
        more for a given (day, app, file). Merging takes the larger value
        rather than the sum, because a backup usually overlaps the current
        data and adding them would double-count the shared days.
        """
        if mode not in (REPLACE, MERGE):
            raise ValueError(f"unknown restore mode: {mode!r}")
        describe_backup(path)          # raises if it isn't a usable backup
        self.flush()

        with self._lock:
            self._conn.commit()        # ATTACH can't run inside a transaction
            self._conn.execute("ATTACH DATABASE ? AS backup", (path,))
            try:
                with self._conn:
                    if mode == REPLACE:
                        self._conn.execute("DELETE FROM activity")
                    self._conn.execute(
                        """
                        INSERT INTO activity (day, app, app_name, file, seconds)
                        SELECT day, app, app_name, file, seconds
                        FROM backup.activity WHERE true
                        ON CONFLICT(day, app, file) DO UPDATE SET
                            seconds = MAX(activity.seconds, excluded.seconds),
                            app_name = excluded.app_name
                        """
                    )
                    self._restore_extras(mode)
                    rows = self._conn.execute(
                        "SELECT COUNT(*) FROM activity").fetchone()[0]
            finally:
                self._conn.execute("DETACH DATABASE backup")
        return rows

    def _restore_extras(self, mode: str) -> None:
        """Timeline and notes, from backups made since those existed.

        Replace takes the backup's as they are. Merge adds what's missing and,
        for a note present on both sides, keeps the current text.
        """
        tables = {r[0] for r in self._conn.execute(
            "SELECT name FROM backup.sqlite_master WHERE type='table'")}
        if mode == REPLACE:
            self._conn.execute("DELETE FROM timeline")
            self._conn.execute("DELETE FROM notes")
            if self._segment:
                self._segment["id"] = None   # its row is gone; re-insert it
        if "timeline" in tables:
            self._conn.execute(
                """
                INSERT INTO timeline (day, start, end, state, app, app_name)
                SELECT day, start, end, state, app, app_name
                FROM backup.timeline WHERE true
                ON CONFLICT(start, state, app) DO UPDATE SET
                    end = MAX(timeline.end, excluded.end)
                """
            )
        if "notes" in tables:
            self._conn.execute(
                "INSERT OR IGNORE INTO notes (ts, text)"
                " SELECT ts, text FROM backup.notes")

    def backup_to(self, path: str) -> None:
        """Write a consistent copy of the database to `path`.

        Uses SQLite's own backup API rather than copying files: in WAL mode most
        recent commits live in the `-wal` sidecar, so a filesystem copy of
        data.db would miss them (and could catch a half-written state). This
        runs against the live connection and produces a single clean file.
        """
        self.flush()
        dest = sqlite3.connect(path)
        try:
            self._conn.backup(dest)
        finally:
            dest.close()
        # Fold the WAL back into the main file so it doesn't grow unbounded.
        try:
            self._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        except sqlite3.Error:
            pass

    # -- reading ----------------------------------------------------------

    def _live_rows(self, start: str, end: str):
        """Buffered-but-unflushed rows that fall in [start, end]."""
        with self._lock:
            for (day, app, app_name, file), seconds in self._buffer.items():
                if start <= day <= end:
                    yield day, app, app_name, file, seconds

    def totals_by_app(self, start: str, end: str, ignore=None) -> list[dict]:
        """Totals per app, busiest first. `ignore` is a set of exes to skip."""
        self.flush()
        ignore = ignore or set()
        cur = self._conn.execute(
            """
            SELECT app, app_name, SUM(seconds) AS total
            FROM activity WHERE day BETWEEN ? AND ?
            GROUP BY app ORDER BY total DESC
            """,
            (start, end),
        )
        rows = {r[0]: {"app": r[0], "app_name": r[1], "seconds": r[2]}
                for r in cur if r[0] not in ignore}
        for _day, app, app_name, _file, seconds in self._live_rows(start, end):
            if app in ignore:
                continue
            entry = rows.setdefault(app, {"app": app, "app_name": app_name, "seconds": 0.0})
            entry["seconds"] += seconds
        return sorted(rows.values(), key=lambda r: r["seconds"], reverse=True)

    def totals_by_app_file(self, start: str, end: str, ignore=None) -> list[dict]:
        """Every (app, file) pair in the range — the grain tags work at.

        One row per file (and one with file='' for an app's untitled time), so
        a tag can hold a whole app, a single file, or a single website.
        """
        self.flush()
        ignore = ignore or set()
        cur = self._conn.execute(
            """
            SELECT app, app_name, file, SUM(seconds) AS total
            FROM activity WHERE day BETWEEN ? AND ?
            GROUP BY app, file
            """,
            (start, end),
        )
        rows = {(r[0], r[2]): {"app": r[0], "app_name": r[1], "file": r[2],
                               "seconds": r[3]}
                for r in cur if r[0] not in ignore}
        for _day, app, app_name, file, seconds in self._live_rows(start, end):
            if app in ignore:
                continue
            entry = rows.setdefault((app, file), {"app": app, "app_name": app_name,
                                                  "file": file, "seconds": 0.0})
            entry["seconds"] += seconds
        return sorted(rows.values(), key=lambda r: r["seconds"], reverse=True)

    def totals_by_tag(self, start: str, end: str, tags, ignore=None) -> list[dict]:
        """Totals per tag for the range (see `fold_tags`)."""
        return fold_tags(self.totals_by_app_file(start, end, ignore), tags)

    def totals_by_file(self, start: str, end: str, apps) -> list[dict]:
        """Totals per file for one app, or across several at once."""
        self.flush()
        app_list = [apps] if isinstance(apps, str) else list(apps)
        if not app_list:
            return []
        placeholders = ",".join("?" * len(app_list))
        cur = self._conn.execute(
            f"""
            SELECT file, SUM(seconds) AS total
            FROM activity WHERE day BETWEEN ? AND ? AND app IN ({placeholders})
            GROUP BY file ORDER BY total DESC
            """,
            (start, end, *app_list),
        )
        rows = {r[0]: {"file": r[0], "seconds": r[1]} for r in cur}
        wanted = set(app_list)
        for _day, a, _app_name, file, seconds in self._live_rows(start, end):
            if a not in wanted:
                continue
            entry = rows.setdefault(file, {"file": file, "seconds": 0.0})
            entry["seconds"] += seconds
        return sorted(rows.values(), key=lambda r: r["seconds"], reverse=True)

    def totals_by_day(self, start: str, end: str) -> dict[str, float]:
        self.flush()
        cur = self._conn.execute(
            """
            SELECT day, SUM(seconds) AS total
            FROM activity WHERE day BETWEEN ? AND ?
            GROUP BY day
            """,
            (start, end),
        )
        out: dict[str, float] = {r[0]: r[1] for r in cur}
        for day, _app, _app_name, _file, seconds in self._live_rows(start, end):
            out[day] = out.get(day, 0.0) + seconds
        return out

    def grand_total(self, start: str, end: str) -> float:
        return sum(r["seconds"] for r in self.totals_by_app(start, end))

    def known_apps(self) -> list[tuple[str, str]]:
        """Distinct (app_key, app_name) ever seen, busiest first."""
        self.flush()
        cur = self._conn.execute(
            """
            SELECT app, app_name, SUM(seconds) AS total
            FROM activity GROUP BY app ORDER BY total DESC
            """
        )
        return [(r[0], r[1]) for r in cur]

    # -- timeline ---------------------------------------------------------

    def timeline_for_day(self, day: str) -> list[dict]:
        """The day's blocks, oldest first: {start, end, state, app, app_name}."""
        self.flush()
        cur = self._conn.execute(
            """
            SELECT start, end, state, app, app_name FROM timeline
            WHERE day = ? ORDER BY start
            """,
            (day,),
        )
        return [{"start": r[0], "end": r[1], "state": r[2], "app": r[3],
                 "app_name": r[4]} for r in cur]

    # -- notes ------------------------------------------------------------

    def notes_for_day(self, day: str) -> dict[str, str]:
        """{"YYYY-MM-DD HH:MM:SS": text} for one day, in time order."""
        with self._lock:
            cur = self._conn.execute(
                "SELECT ts, text FROM notes WHERE ts LIKE ? ORDER BY ts",
                (f"{day} %",),
            )
            return dict(cur.fetchall())

    def save_note(self, ts: str, text: str, replaces: str | None = None) -> str:
        """Store a note at `ts` and return the key it was saved under.

        `replaces` is the note's old key when editing, so moving a note to
        another time doesn't leave the original behind. A different note
        already at `ts` is never overwritten; the new one moves a second later.
        """
        when = dt.datetime.strptime(ts, NOTE_TS_FORMAT)
        with self._lock, self._conn:
            if replaces:
                self._conn.execute("DELETE FROM notes WHERE ts = ?", (replaces,))
            while self._conn.execute(
                    "SELECT 1 FROM notes WHERE ts = ?", (ts,)).fetchone():
                when += dt.timedelta(seconds=1)
                ts = when.strftime(NOTE_TS_FORMAT)
            self._conn.execute("INSERT INTO notes (ts, text) VALUES (?, ?)",
                               (ts, text))
        return ts

    def delete_note(self, ts: str) -> None:
        with self._lock, self._conn:
            self._conn.execute("DELETE FROM notes WHERE ts = ?", (ts,))


def _local_day(epoch: float) -> str:
    return dt.datetime.fromtimestamp(epoch).date().isoformat()


def _next_midnight(epoch: float) -> float:
    day = dt.datetime.fromtimestamp(epoch).date() + dt.timedelta(days=1)
    return dt.datetime.combine(day, dt.time()).timestamp()


def today_str() -> str:
    return dt.date.today().isoformat()
