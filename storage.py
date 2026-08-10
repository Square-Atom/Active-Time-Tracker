"""SQLite storage for focus time.

We aggregate at the (day, app, file) grain. Every active second increments the
`seconds` counter for the matching row. Writes are buffered in memory and
flushed periodically (and on pause/quit) so we're not committing every second.
"""

from __future__ import annotations

import datetime as dt
import sqlite3
import threading
from collections import defaultdict

import config


class Storage:
    def __init__(self, db_path: str = config.DB_PATH):
        self.db_path = db_path
        self._lock = threading.Lock()
        # (day, app, app_name, file) -> accumulated seconds not yet written
        self._buffer: dict[tuple[str, str, str, str], float] = defaultdict(float)
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
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
