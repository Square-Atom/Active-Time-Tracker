"""Check GitHub for a newer release.

Read-only and dependency-free: it asks the GitHub API for the latest published
release and compares its tag with `config.APP_VERSION`. The app never downloads
or installs anything — if an update exists we just point the user at the
Releases page so they can grab it themselves.
"""

from __future__ import annotations

import json
import logging
import re
import threading
import urllib.error
import urllib.request
from dataclasses import dataclass

import config

GITHUB_REPO = "Square-Atom/Active-Time-Tracker"
RELEASES_PAGE = f"https://github.com/{GITHUB_REPO}/releases/latest"
_API_URL = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
_TIMEOUT = 8  # seconds

_log = logging.getLogger(__name__)


@dataclass
class UpdateResult:
    #  "update" | "current" | "none" | "error"
    status: str
    latest: str = ""       # version string of the latest release, e.g. "1.1.0"
    url: str = RELEASES_PAGE
    message: str = ""      # human-readable detail (used for errors)
    notes: str = ""        # the release's own words, shown instead of the
                           # default blurb when there's something to say

    @property
    def has_update(self) -> bool:
        return self.status == "update"


def parse_version(text: str) -> tuple[int, ...]:
    """'v1.2.3-beta' -> (1, 2, 3). Non-numeric parts are ignored."""
    nums = re.findall(r"\d+", (text or "").strip().lstrip("vV"))
    return tuple(int(n) for n in nums[:4]) or (0,)


def is_newer(latest: str, current: str) -> bool:
    a, b = parse_version(latest), parse_version(current)
    size = max(len(a), len(b))
    a += (0,) * (size - len(a))
    b += (0,) * (size - len(b))
    return a > b


ANNOUNCE_START = "<!--announce-->"
ANNOUNCE_END = "<!--/announce-->"
_MAX_NOTE_LINES = 10
_MAX_NOTE_CHARS = 700


def announcement(body: str | None) -> str:
    """The message to show in the update popup, taken from the release notes.

    Whatever a release says is shown to everyone who has the app, so it doubles
    as a way to get a word out with an important update. Wrapping part of the
    notes in `<!--announce-->…<!--/announce-->` picks out just that part, which
    keeps a long changelog out of a small dialog. With no markers the whole
    body is used, trimmed to something a dialog can hold; with nothing at all
    the popup falls back to its standard wording.

    Rendered as plain text — never interpreted as markup.
    """
    text = (body or "").strip()
    if not text:
        return ""
    if ANNOUNCE_START in text:
        text = text.split(ANNOUNCE_START, 1)[1]
        text = text.split(ANNOUNCE_END, 1)[0]
    lines = [ln.rstrip() for ln in text.strip().splitlines()]
    # Drop markdown noise that reads badly as plain text.
    lines = [ln for ln in lines if set(ln.strip()) not in ({"-"}, {"="}, set())]
    if len(lines) > _MAX_NOTE_LINES:
        lines = lines[:_MAX_NOTE_LINES] + ["…"]
    text = "\n".join(lines).strip()
    if len(text) > _MAX_NOTE_CHARS:
        text = text[:_MAX_NOTE_CHARS].rstrip() + "…"
    return text


def check(current_version: str | None = None) -> UpdateResult:
    """Query GitHub. Never raises — network problems come back as 'error'."""
    current = current_version or config.APP_VERSION
    req = urllib.request.Request(
        _API_URL,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": f"ActiveTimeTracker/{current}",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return UpdateResult("none", message="No releases published yet.")
        if exc.code in (403, 429):
            return UpdateResult(
                "error", message="GitHub rate limit reached. Try again later.")
        _log.warning("Update check failed: HTTP %s", exc.code)
        return UpdateResult("error", message=f"GitHub returned HTTP {exc.code}.")
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        _log.info("Update check failed: %s", exc)
        return UpdateResult("error", message="Couldn't reach GitHub. Check your connection.")
    except (ValueError, json.JSONDecodeError):
        return UpdateResult("error", message="Unexpected response from GitHub.")

    tag = (data.get("tag_name") or data.get("name") or "").strip()
    url = data.get("html_url") or RELEASES_PAGE
    if not tag:
        return UpdateResult("none", url=url, message="No releases published yet.")
    latest = tag.lstrip("vV")
    notes = announcement(data.get("body"))
    if is_newer(latest, current):
        return UpdateResult("update", latest=latest, url=url, notes=notes)
    return UpdateResult("current", latest=latest, url=url, notes=notes)


def check_async(callback, current_version: str | None = None) -> None:
    """Run `check` off the UI thread; `callback(UpdateResult)` gets the result.

    The callback runs on the worker thread — Tk callers should marshal back to
    the main thread (e.g. `root.after(0, ...)`).
    """
    def run():
        try:
            callback(check(current_version))
        except Exception:  # never let a background thread crash the app
            _log.exception("Update check thread failed")
            callback(UpdateResult("error", message="Update check failed."))

    threading.Thread(target=run, name="update-check", daemon=True).start()
