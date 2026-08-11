"""Daily rotating backups of the tracked-time database.

Losing `data.db` means losing history that can't be recreated, so the app keeps
a few dated copies. Backups go to `<data dir>/backups` by default; point
`backup_dir` at a synced folder (OneDrive, Nextcloud, …) to get off-machine
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

import config

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


def is_due(cfg: config.Config, today: str | None = None) -> bool:
    """True when no backup exists for today yet."""
    if not cfg.backup_enabled:
        return False
    today = today or dt.date.today().isoformat()
    have = existing(cfg)
    return not have or have[0] < today


def run(storage, cfg: config.Config, today: str | None = None) -> str | None:
    """Write today's backup and prune old ones. Returns the .db path, or None.

    Never raises: a failed backup is logged and otherwise invisible, because it
    must never take the tracker down with it.
    """
    stamp = today or dt.date.today().isoformat()
    target = backup_dir(cfg)
    try:
        os.makedirs(target, exist_ok=True)
        db_path = os.path.join(target, f"{_DB_PREFIX}{stamp}.db")
        # Write to a temp name first so an interrupted run can't leave a
        # half-written file looking like a good backup.
        tmp = db_path + ".part"
        storage.backup_to(tmp)
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


def safety_copy(storage, cfg: config.Config) -> str | None:
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
        storage.backup_to(tmp)
        os.replace(tmp, path)
        _log.info("Pre-restore snapshot: %s", path)
        return path
    except Exception:
        _log.exception("Could not write the pre-restore snapshot")
        return None


def maybe_run(storage, cfg: config.Config) -> str | None:
    """Back up if enabled and none exists for today."""
    if not is_due(cfg):
        return None
    return run(storage, cfg)
