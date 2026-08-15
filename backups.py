"""Daily rotating backups of the tracked-time database.

Losing `data.db` means losing history that can't be recreated, so the app keeps
a few dated copies. Backups go to `<data dir>/backups` by default; point
`backup_dir` at a synced folder (OneDrive, Google Drive, …) to get off-machine
safety, since a copy on the same disk won't survive a drive failure.

The actual copy is made by `Storage.backup_to`, which uses SQLite's backup API —
see the note there for why a plain file copy is wrong in WAL mode.
"""

from __future__ import annotations

import datetime as dt
import logging
import os
import re
import shutil
import time

import config
import storage

_DB_PREFIX, _CFG_PREFIX = "data-", "config-"
_STAMP_RE = re.compile(r"^(?:data|config)-(\d{4}-\d{2}-\d{2})\.(?:db|json)$")

_log = logging.getLogger(__name__)


def backup_dir(cfg: config.Config) -> str:
    """Where backups live — the configured folder, or the default."""
    custom = (cfg.backup_dir or "").strip()
    if custom:
        return os.path.expanduser(custom)
    return os.path.join(config.APP_DIR, "backups")


def existing(cfg: config.Config) -> list[str]:
    """Backup dates present on disk, newest first (YYYY-MM-DD strings)."""
    path = backup_dir(cfg)
    try:
        names = os.listdir(path)
    except OSError:
        return []
    stamps = {m.group(1) for n in names if (m := _STAMP_RE.match(n))}
    return sorted(stamps, reverse=True)


def _db_path(cfg: config.Config, stamp: str) -> str:
    return os.path.join(backup_dir(cfg), f"{_DB_PREFIX}{stamp}.db")


def is_due(cfg: config.Config, today: str | None = None,
           now: float | None = None) -> bool:
    """True when today has no backup yet, or the one it has has gone stale.

    Backing up only once a day left everything since that morning unprotected —
    a day's work could be lost with nothing to restore from. Today's file is
    refreshed every `backup_interval_hours` instead, which caps the exposure.
    """
    if not cfg.backup_enabled:
        return False
    today = today or dt.date.today().isoformat()
    have = existing(cfg)
    if not have or have[0] < today:
        return True
    try:
        age = (now or time.time()) - os.path.getmtime(_db_path(cfg, today))
    except OSError:
        return True                      # today's file is listed but unreadable
    return age >= max(0.0, float(cfg.backup_interval_hours)) * 3600


def _lost_history(new_path: str, old_path: str) -> str | None:
    """Describe what a replacement would throw away, or None if it's safe.

    Refreshing today's backup through the day means we can overwrite a good
    copy with a bad one: if the live database is reverted or damaged, the very
    next backup would bake that in and destroy the last good copy. So a
    replacement that has *less* history than what's already there is refused.
    """
    if not os.path.exists(old_path):
        return None
    try:
        new = storage.describe_backup(new_path)
        old = storage.describe_backup(old_path)
    except storage.BadBackup:
        return None                      # can't compare; let the write proceed
    if new["seconds"] < old["seconds"] or new["rows"] < old["rows"]:
        return (f"{old['rows']} rows / {old['seconds'] / 3600:.2f}h on disk vs "
                f"{new['rows']} rows / {new['seconds'] / 3600:.2f}h now")
    return None


def run(storage_obj, cfg: config.Config, today: str | None = None,
        now: float | None = None, force: bool = False) -> str | None:
    """Write today's backup and prune old ones. Returns the .db path, or None.

    Never raises: a failed backup is logged and otherwise invisible, because it
    must never take the tracker down with it.

    `force` skips the shrink check — used by the manual "Back up now" button,
    where the user has explicitly asked for the current state whatever it holds.
    """
    stamp = today or dt.date.today().isoformat()
    target = backup_dir(cfg)
    try:
        os.makedirs(target, exist_ok=True)
        db_path = _db_path(cfg, stamp)
        # Write to a temp name first so an interrupted run can't leave a
        # half-written file looking like a good backup.
        tmp = db_path + ".part"
        storage_obj.backup_to(tmp)

        if not force:
            lost = _lost_history(tmp, db_path)
            if lost:
                os.remove(tmp)
                _log.warning(
                    "Backup skipped: today's copy would lose history (%s). "
                    "Keeping the existing file.", lost)
                return None

        os.replace(tmp, db_path)
        if os.path.exists(config.CONFIG_PATH):
            shutil.copy2(config.CONFIG_PATH,
                         os.path.join(target, f"{_CFG_PREFIX}{stamp}.json"))
        prune(cfg)
        _log.info("Backup written: %s", db_path)
        return db_path
    except Exception:
        _log.exception("Backup failed")
        return None


def prune(cfg: config.Config) -> None:
    """Keep only the newest `backup_keep` dates."""
    keep = max(1, int(cfg.backup_keep or 1))
    target = backup_dir(cfg)
    for stamp in existing(cfg)[keep:]:
        for name in (f"{_DB_PREFIX}{stamp}.db", f"{_CFG_PREFIX}{stamp}.json"):
            try:
                os.remove(os.path.join(target, name))
            except OSError:
                pass


def list_backups(cfg: config.Config) -> list[tuple[str, str]]:
    """[(date, full path)] for the dated backups on disk, newest first."""
    target = backup_dir(cfg)
    return [(stamp, os.path.join(target, f"{_DB_PREFIX}{stamp}.db"))
            for stamp in existing(cfg)]


def safety_copy(storage_obj, cfg: config.Config) -> str | None:
    """Snapshot the current data before a restore overwrites it.

    Named apart from the dated backups so it never displaces today's, and
    never disappears in rotation — this is the undo for a mistaken restore.
    """
    target = backup_dir(cfg)
    stamp = dt.datetime.now().strftime("%Y-%m-%d-%H%M%S")
    path = os.path.join(target, f"pre-restore-{stamp}.db")
    try:
        os.makedirs(target, exist_ok=True)
        tmp = path + ".part"
        storage_obj.backup_to(tmp)
        os.replace(tmp, path)
        _log.info("Pre-restore snapshot: %s", path)
        return path
    except Exception:
        _log.exception("Could not write the pre-restore snapshot")
        return None


def maybe_run(storage_obj, cfg: config.Config) -> str | None:
    """Back up if enabled and today's copy is missing or stale."""
    if not is_due(cfg):
        return None
    return run(storage_obj, cfg)


def newest_sound_backup(cfg: config.Config) -> tuple[str, str] | None:
    """The most recent backup that passes an integrity check, as (date, path)."""
    for stamp, path in list_backups(cfg):
        if os.path.exists(path) and storage.integrity_problem(path) is None:
            return stamp, path
    return None


def repair_if_corrupt(cfg: config.Config, db_path: str | None = None) -> str | None:
    """Swap a damaged database for the newest sound backup, before it's opened.

    Returns a sentence describing what happened, or None if nothing was wrong.

    Must run while nothing has the database open — at startup, after the
    single-instance guard. The damaged files are moved aside rather than
    deleted: they may still hold the newest work, and a corrupt database is
    better than no database if there's nothing to restore from.
    """
    db_path = db_path or config.DB_PATH
    problem = storage.integrity_problem(db_path)
    if problem is None:
        return None
    _log.error("Database failed its integrity check: %s", problem.splitlines()[0])

    candidate = newest_sound_backup(cfg)
    if candidate is None:
        _log.error("No sound backup to recover from; leaving the database in place")
        return ("Your data file is damaged and there's no healthy backup to "
                "restore from. Tracking will continue, but please check the "
                "backups folder.")

    stamp, source = candidate
    quarantine = os.path.join(os.path.dirname(db_path) or ".",
                              "damaged-" + dt.datetime.now().strftime("%Y-%m-%d-%H%M%S"))
    try:
        os.makedirs(quarantine, exist_ok=True)
        for suffix in ("", "-wal", "-shm"):
            part = db_path + suffix
            if os.path.exists(part):
                # Move every part together: leaving a sidecar behind is what
                # caused the damage in the first place.
                shutil.move(part, os.path.join(quarantine,
                                               os.path.basename(part)))
        shutil.copy2(source, db_path)
    except OSError:
        _log.exception("Could not recover the database")
        return ("Your data file is damaged and recovering it failed. Please "
                "check the backups folder.")

    _log.warning("Recovered from %s; damaged files kept in %s", source, quarantine)
    return (f"Your data file was damaged, so it was restored from the backup "
            f"of {stamp}. The damaged copy was kept in "
            f"{os.path.basename(quarantine)} in case it's needed.")


def run_on_exit(storage_obj, cfg: config.Config) -> str | None:
    """Capture the final state as the app closes.

    Ignores the interval — quitting is exactly when the newest work is at risk,
    and the alternative is losing everything since the last hourly run. Still
    goes through the usual shrink check, so quitting after something has damaged
    the database can't overwrite a good copy.
    """
    if not cfg.backup_enabled:
        return None
    return run(storage_obj, cfg)
