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


class Storage:
    def __init__(self, db_path: str = config.DB_PATH):
        self.db_path = db_path
        self._lock = threading.Lock()
        # (day, app, app_name, file) -> accumulated seconds not yet written
        self._buffer: dict[tuple[str, str, str, str], float] = defaultdict(float)
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

    # -- writing ----------------------------------------------------------

    def add_seconds(self, day: str, app: str, app_name: str, file: str, seconds: float) -> None:
        """Buffer active time for a (day, app, file)."""
        with self._lock:
            self._buffer[(day, app, app_name, file)] += seconds

    def _write(self, items) -> None:
        """Persist buffered (key, seconds) pairs in one transaction."""
        with self._conn:
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
            if not self._buffer:
                return
            items = list(self._buffer.items())
            self._buffer.clear()
        self._write(items)

    def close(self) -> None:
        self.flush()
        self._conn.close()

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
                    rows = self._conn.execute(
                        "SELECT COUNT(*) FROM activity").fetchone()[0]
            finally:
                self._conn.execute("DETACH DATABASE backup")
        return rows

    def backup_to(self, path: str) -> None:
        """Write a consistent copy of the database to `path`.

        Uses SQLite's own backup API rather than copying files: in WAL mode most
        recent commits live in the `-wal` sidecar, so a filesystem copy of
        data.db would miss them (and could catch a half-written state). This
        runs against the live connection and produces a single clean file.
        """
        with self._lock:
            buffered = list(self._buffer.items())
            self._buffer.clear()
        if buffered:
            self._write(buffered)
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

    def totals_by_app(self, start: str, end: str, merge_map=None, ignore=None) -> list[dict]:
        """Totals per app. `merge_map` (member_exe -> (group_key, group_name))
        folds member apps into a single group row at read time. `ignore` is a set
        of exe names to exclude entirely."""
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

        if not merge_map:
            return sorted(rows.values(), key=lambda r: r["seconds"], reverse=True)

        folded: dict[str, dict] = {}
        for entry in rows.values():
            if entry["app"] in merge_map:
                key, name = merge_map[entry["app"]]
            else:
                key, name = entry["app"], entry["app_name"]
            f = folded.setdefault(key, {"app": key, "app_name": name, "seconds": 0.0})
            f["seconds"] += entry["seconds"]
        return sorted(folded.values(), key=lambda r: r["seconds"], reverse=True)

    def totals_by_file(self, start: str, end: str, apps) -> list[dict]:
        """Totals per file across one app or several (a merged group)."""
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


def today_str() -> str:
    return dt.date.today().isoformat()
