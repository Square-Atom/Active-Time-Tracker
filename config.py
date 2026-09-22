"""Configuration: paths, defaults, friendly names, and title-parsing rules.

Config lives in a per-user data directory (see `_data_dir`) as config.json, so it
survives code updates. Users can edit the JSON to add/adjust file-parsing rules.
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from dataclasses import dataclass, field

APP_NAME = "ActiveTimeTracker"
APP_VERSION = "1.8.0"  # keep in sync with the git tag used for releases
_OLD_APP_NAME = "WorkTimeTracker"  # for one-time migration of existing data


def _base_dir() -> str:
    """Platform-appropriate per-user data directory root."""
    if sys.platform == "win32":
        return os.environ.get("APPDATA", os.path.expanduser("~"))
    if sys.platform == "darwin":
        return os.path.expanduser("~/Library/Application Support")
    return os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config"))


APP_DIR = os.path.join(_base_dir(), APP_NAME)
_OLD_APP_DIR = os.path.join(_base_dir(), _OLD_APP_NAME)

# One-time migration: if the old "WorkTimeTracker" folder exists and the new one
# doesn't yet, move it over so existing history is preserved after the rename.
if not os.path.exists(APP_DIR) and os.path.isdir(_OLD_APP_DIR):
    try:
        os.rename(_OLD_APP_DIR, APP_DIR)
    except OSError:
        pass

os.makedirs(APP_DIR, exist_ok=True)

CONFIG_PATH = os.path.join(APP_DIR, "config.json")
DB_PATH = os.path.join(APP_DIR, "data.db")

# Friendly display names for common apps. Anything not listed falls back to
# the exe name with ".exe" stripped and title-cased.
FRIENDLY_NAMES = {
    "activetimetracker.exe": "Active Time Tracker",
    "activetimetracker": "Active Time Tracker",  # macOS/Linux binary name
    "worktimetracker.exe": "Active Time Tracker",  # legacy rows (pre-rename)
    "photoshop.exe": "Photoshop",
    "pyxeledit.exe": "Pyxel Edit",
    "aseprite.exe": "Aseprite",
    "krita.exe": "Krita",
    "clipstudiopaint.exe": "Clip Studio Paint",
    "illustrator.exe": "Illustrator",
    "afterfx.exe": "After Effects",
    "blender.exe": "Blender",
    "godot.exe": "Godot",
    "godot_console.exe": "Godot",
    "unity.exe": "Unity",
    "code.exe": "VS Code",
    "devenv.exe": "Visual Studio",
    "notepad++.exe": "Notepad++",
    "notepad.exe": "Notepad",
    "sublime_text.exe": "Sublime Text",
    "obsidian.exe": "Obsidian",
    "chrome.exe": "Chrome",
    "msedge.exe": "Edge",
    "firefox.exe": "Firefox",
    "explorer.exe": "File Explorer",
    "wt.exe": "Windows Terminal",
    "powershell.exe": "PowerShell",
    "pwsh.exe": "PowerShell",
    "cmd.exe": "Command Prompt",
    "winword.exe": "Word",
    "excel.exe": "Excel",
    "powerpnt.exe": "PowerPoint",
}

# Separators between an app name and the filename in a window title.
#   HARD — characters a filename can never contain, so they always split.
#   SOFT — dashes, pipes and arrows, which *do* appear in filenames
#          (clockwork-workshop.pyxel). These only split when surrounded by
#          whitespace, so " - " separates but "clockwork-workshop" survives.
_HARD_SEP = r"[\\/\[]"
_SOFT_SEP = "\\s[-\u2013\u2014|>\u2192]\\s"
_TITLE_PREFIX = rf"(?:.*(?:{_HARD_SEP}|{_SOFT_SEP})|^)\s*"


def ext_rule(*exts: str) -> str:
    """Build a regex that grabs the filename token ending in one of `exts`.

    It takes the token *after the last separator*, so an app name or path in the
    title is stripped away while the filename itself stays intact — including
    hyphens, underscores and spaces. Works whether the file appears at the start
    of the title (e.g. Photoshop) or the end ("App - file.ext",
    "App [C:\\path\\file.ext]").
    """
    group = "|".join(exts)
    return rf'{_TITLE_PREFIX}(?P<file>[^\\/:*?"<>|\[\]]+?\.(?:{group}))'


def path_ext_rule(*exts: str) -> str:
    """Like `ext_rule`, but captures a *full path* when the title shows one.

    Only matches when the token is rooted (``C:\\…``, ``/…`` or ``~/…``), so two
    same-named files in different folders stay distinct. Pair it before the
    plain `ext_rule` so bare filenames still work as a fallback.
    """
    group = "|".join(exts)
    return (rf'(?P<file>(?:[A-Za-z]:[\\/]|\\\\|/|~[\\/])'
            rf'[^:*?"<>|\r\n\[\]]*?\.(?:{group}))')


# Generic fallbacks, tried in order: a rooted path first, then a bare filename.
GENERIC_PATH_RE = re.compile(
    r'(?P<file>(?:[A-Za-z]:[\\/]|\\\\|/|~[\\/])[^:*?"<>|\r\n\[\]]*?\.[A-Za-z0-9]{1,6})')
GENERIC_FILE_RE = re.compile(
    rf'{_TITLE_PREFIX}(?P<file>[^\\/:*?"<>|\r\n]+?\.[A-Za-z0-9]{{1,6}})')


# --- browser "which site am I on" detection ---------------------------------
# Window titles never contain the URL, only the page title (e.g.
# "Facebook - Google Chrome"). We strip the browser's own suffix and then take
# the site name from the page title. See `parse_site`.

# Trailing browser branding. Only Edge inserts a profile segment before its
# name ("Page - Personal - Microsoft Edge"), so that allowance is Edge-only —
# applying it generally would swallow the real site in "… - YouTube - Chrome".
_BRANDS = (r"Google\s+Chrome|Chromium|Mozilla\s+Firefox|Firefox|Brave"
           r"|Opera(?:\s+\w+)?|Vivaldi|Safari|Arc|Zen\s+Browser")
_EDGE = r"Microsoft​?\s*Edge"
_BROWSER_SUFFIX_RE = re.compile(
    rf"\s*[-—–|]\s*(?:(?:{_BRANDS})|(?:[^-—–|]{{1,30}}\s*[-—–|]\s*)?(?:{_EDGE}))\s*$",
    re.IGNORECASE,
)
# A window showing nothing but the browser's own name has no site to report.
_BRAND_ONLY_RE = re.compile(rf"^\s*(?:{_BRANDS}|{_EDGE})\s*$", re.IGNORECASE)
# "…and 4 more pages" (Edge), and leading unread counters like "(3) ".
_MORE_PAGES_RE = re.compile(r"\s+and\s+\d+\s+more\s+pages?\s*$", re.IGNORECASE)
_LEADING_COUNT_RE = re.compile(r"^\s*\(\d+\)\s*")
# Separators that page titles use between the content and the site name.
_TITLE_SPLIT_RE = re.compile(r"\s+(?:[-—–|·•»]|::|:|/)\s+")

# Titles that put the site first, or otherwise need a canonical spelling. Keys
# are lowercase; matched against any segment of the page title.
KNOWN_SITES = {
    "youtube": "YouTube", "github": "GitHub", "gitlab": "GitLab",
    "facebook": "Facebook", "instagram": "Instagram", "reddit": "Reddit",
    "stack overflow": "Stack Overflow", "x": "X", "twitter": "Twitter",
    "gmail": "Gmail", "google docs": "Google Docs", "google drive": "Google Drive",
    "google sheets": "Google Sheets", "google slides": "Google Slides",
    "google search": "Google", "google maps": "Google Maps",
    "wikipedia": "Wikipedia", "linkedin": "LinkedIn", "twitch": "Twitch",
    "discord": "Discord", "notion": "Notion", "chatgpt": "ChatGPT",
    "claude": "Claude", "netflix": "Netflix", "spotify": "Spotify",
    "steam": "Steam", "figma": "Figma", "trello": "Trello", "jira": "Jira",
    "slack": "Slack", "zoom": "Zoom", "tiktok": "TikTok", "medium": "Medium",
    "pinterest": "Pinterest", "artstation": "ArtStation", "behance": "Behance",
    "dribbble": "Dribbble", "deviantart": "DeviantArt", "itch.io": "itch.io",
    "hacker news": "Hacker News", "outlook": "Outlook", "microsoft teams": "Teams",
    "stack exchange": "Stack Exchange", "codepen": "CodePen", "replit": "Replit",
    "udemy": "Udemy", "coursera": "Coursera", "amazon": "Amazon",
    "bing": "Bing", "duckduckgo": "DuckDuckGo", "whatsapp": "WhatsApp",
    "messenger": "Messenger", "telegram": "Telegram", "google": "Google",
}

_MAX_SITE_LEN = 40


def parse_site(title: str) -> str:
    """Best-effort site name from a browser window title.

    Titles carry the page title, not the URL, so this is a heuristic: prefer a
    known site appearing anywhere in the title, else fall back to the last
    segment (the usual place for the site name, e.g. "Video - YouTube").
    Returns '' when there's nothing useful, which counts as app-level time.
    """
    if not title:
        return ""
    page = _BROWSER_SUFFIX_RE.sub("", title.strip())
    page = _MORE_PAGES_RE.sub("", page)
    page = _LEADING_COUNT_RE.sub("", page).strip()
    if not page or _BRAND_ONLY_RE.match(page):
        return ""

    segments = [s.strip() for s in _TITLE_SPLIT_RE.split(page) if s.strip()]
    if not segments:
        return ""

    # A known site anywhere in the title wins (handles "GitHub - user/repo",
    # where the site name comes first).
    for seg in segments:
        canon = KNOWN_SITES.get(seg.casefold())
        if canon:
            return canon
        if seg.casefold().startswith("r/"):
            return "Reddit"

    # Otherwise the last segment is conventionally the site.
    site = segments[-1]
    if len(site) > _MAX_SITE_LEN:
        site = site[:_MAX_SITE_LEN - 1].rstrip() + "…"
    return site


# Per-app rules for extracting the open file from the window title.
#   list of regex patterns -> first pattern with a named group `file` wins
#   ["app"]                 -> track at app level only (no per-file split)
#   (missing / null)        -> use GENERIC_FILE_RE fallback
DEFAULT_FILE_RULES: dict[str, list[str]] = {
    # Editors that name the workspace/project: capture it as `folder` so two
    # same-named files in different projects stay separate.
    # `(?:(?!\s-\s).)+` = "anything up to the next ' - ' separator", so
    # hyphenated names (my-file.py, Work-Time-Tracker) survive intact.
    "code.exe": [
        r"^[●•\*\s]*(?P<file>.+?)\s+-\s+(?P<folder>(?:(?!\s-\s).)+)\s+-\s+.*Visual Studio Code$",
        r"^[●•\*\s]*(?P<file>.+?)\s+-\s+.*Visual Studio Code$",
    ],
    "devenv.exe": [
        r"^(?P<file>.+?)\s+-\s+(?P<folder>(?:(?!\s-\s).)+)\s+-\s+Microsoft Visual Studio",
        r"^(?P<file>.+?)\s+-\s+Microsoft Visual Studio",
    ],
    "sublime_text.exe": [r"^(?P<file>.+?)\s+.\s+.*Sublime Text$"],
    "notepad++.exe": [r"^\*?(?P<file>.+?) - Notepad\+\+"],  # title carries full path
    "notepad.exe": [r"^\*?(?P<file>.+?) - Notepad$"],
    "obsidian.exe": [r"^(?P<file>.+?) - (?P<folder>(?:(?!\s-\s).)+) - Obsidian$",
                     r"^(?P<file>.+?) - .* - Obsidian$"],
    # Creative apps: prefer a full path when the title shows one, else filename.
    "pyxeledit.exe": [path_ext_rule("pyxel"), ext_rule("pyxel")],
    "aseprite.exe": [path_ext_rule("aseprite", "ase", "png", "gif", "bmp", "jpe?g"),
                     ext_rule("aseprite", "ase", "png", "gif", "bmp", "jpe?g")],
    "photoshop.exe": [path_ext_rule("psd", "psb", "png", "jpe?g", "tiff?", "gif", "webp", "bmp"),
                      ext_rule("psd", "psb", "png", "jpe?g", "tiff?", "gif", "webp", "bmp")],
    "illustrator.exe": [path_ext_rule("ai", "svg", "pdf", "eps"),
                        ext_rule("ai", "svg", "pdf", "eps")],
    "krita.exe": [path_ext_rule("kra", "png", "jpe?g", "psd", "tiff?"),
                  ext_rule("kra", "png", "jpe?g", "psd", "tiff?")],
    "clipstudiopaint.exe": [path_ext_rule("clip", "png", "psd"),
                            ext_rule("clip", "png", "psd")],
    "blender.exe": [path_ext_rule("blend"), ext_rule("blend")],
    "afterfx.exe": [path_ext_rule("aep"), ext_rule("aep")],
    "winword.exe": [r"^(?P<file>.+?) - Word$"],
    "excel.exe": [r"^(?P<file>.+?) - Excel$"],
    "powerpnt.exe": [r"^(?P<file>.+?) - PowerPoint$"],
    "activetimetracker.exe": ["app"],
    "activetimetracker": ["app"],
    "worktimetracker.exe": ["app"],
    # Browsers: split by website (read from the page title — see `parse_site`).
    "chrome.exe": ["site"],
    "msedge.exe": ["site"],
    "firefox.exe": ["site"],
    "brave.exe": ["site"],
    "opera.exe": ["site"],
    "vivaldi.exe": ["site"],
    "chromium.exe": ["site"],
    "arc.exe": ["site"],
    "safari": ["site"],           # macOS
    "google chrome": ["site"],    # macOS binary names
    "firefox": ["site"],
    "microsoft edge": ["site"],
    # Shell: app-level only (titles are folder names, too noisy).
    "explorer.exe": ["app"],
}

DEFAULTS = {
    "idle_timeout_seconds": 10,
    "poll_interval_seconds": 1.0,
    "flush_interval_seconds": 15,
    "autostart": True,
    "ignore_apps": [],  # exe names to never track, e.g. ["lockapp.exe"]
    "file_rules": {},    # user overrides merged over DEFAULT_FILE_RULES
    # Tags: named buckets of apps / files / sites, used by the chart's Tags
    # mode. Applied at read time, so tagging is retroactive and reversible.
    # e.g. [{"name": "Work", "items": [{"app": "code.exe"},
    #                                  {"app": "chrome.exe", "file": "GitHub"}]}]
    "tags": [],
    # How the Tags window lists them: "recent" (newest addition first) or "name".
    "tag_sort": "recent",
    "check_updates_on_startup": True,
    # Daily rotating backups of data.db (+ config.json).
    "backup_enabled": True,
    "backup_dir": "",      # "" = <data dir>/backups; set a synced folder for
                           # off-machine safety (OneDrive, Google Drive, …)
    "backup_keep": 7,
    # Today's backup is refreshed this often, so a loss costs at most this long
    # rather than everything since the morning. A backup measures ~34ms to a
    # network drive, so a short interval is cheap.
    "backup_interval_minutes": 30,
    # Hand-picked bar colours, app key -> "#rrggbb". Anything not listed gets a
    # stable colour derived from its name.
    "app_colors": {},
    # Focus reminders: after this long in one app, and then every so often,
    # a click-to-add-a-note popup. Off unless asked for.
    "notify_enabled": False,
    "notify_first_minutes": 5,
    "notify_repeat_minutes": 15,
    # Day view timeline (focus blocks + notes) and the global "new note" hotkey,
    # e.g. "Ctrl+Alt+N". "" = no hotkey.
    "timeline_enabled": True,
    "note_hotkey": "",
}

TAG_PREFIX = "tag::"   # synthetic chart key for a tag row
BY_RECENT = "recent"   # tag orderings: newest addition first …
BY_NAME = "name"       # … or A-Z


def _now() -> int:
    """Epoch seconds, as a seam tests can hold still."""
    return int(time.time())


def tag_key(name: str) -> str:
    return TAG_PREFIX + name


def item_key(app: str, file: str | None = None) -> tuple[str, str | None]:
    """Normalised identity of something taggable.

    `file=None` means the whole app (all of its time, whatever the file); a
    string — including "" — means that one file/site inside the app, where ""
    is the app's untitled time, the "(no file)" row in the breakdown.
    """
    return ((app or "").strip().lower(), file)


def _stamp(value) -> int:
    """A stored `added`/`created` time, or 0 when it's missing or nonsense."""
    try:
        return max(0, int(float(value)))
    except (TypeError, ValueError):
        return 0


def _item(app: str, file: str | None, added: int) -> dict:
    entry = {"app": app} if file is None else {"app": app, "file": file}
    if added:
        entry["added"] = added
    return entry


def _clean_items(raw) -> list[dict]:
    """Stored items -> normalised, de-duplicated [{app, file?, added?}]."""
    out: list[dict] = []
    seen: set[tuple[str, str | None]] = set()
    for entry in raw or []:
        if isinstance(entry, str):          # tolerate a bare exe name
            entry = {"app": entry}
        if not isinstance(entry, dict):
            continue
        app, file = item_key(entry.get("app", ""), entry.get("file"))
        if not app or (app, file) in seen:
            continue
        seen.add((app, file))
        out.append(_item(app, file, _stamp(entry.get("added"))))
    return out


def clean_tags(raw) -> list[dict]:
    """Stored tags -> normalised [{name, items}], dropping unusable entries.

    Names are kept as typed but must be unique, since a tag is addressed by
    its name everywhere else (chart key, colour, menus).
    """
    out: list[dict] = []
    seen: set[str] = set()
    for entry in raw or []:
        if not isinstance(entry, dict):
            continue
        name = (entry.get("name") or "").strip()
        if not name or name.casefold() in seen:
            continue
        seen.add(name.casefold())
        tag = {"name": name, "items": _clean_items(entry.get("items"))}
        created = _stamp(entry.get("created"))
        if created:
            tag["created"] = created
        out.append(tag)
    return out


@dataclass
class Config:
    idle_timeout_seconds: float = 10
    poll_interval_seconds: float = 1.0
    flush_interval_seconds: float = 15
    autostart: bool = True
    ignore_apps: list[str] = field(default_factory=list)
    file_rules: dict[str, list[str]] = field(default_factory=dict)
    tags: list[dict] = field(default_factory=list)
    tag_sort: str = BY_RECENT
    check_updates_on_startup: bool = True
    backup_enabled: bool = True
    backup_dir: str = ""
    backup_keep: int = 7
    backup_interval_minutes: int = 30
    app_colors: dict[str, str] = field(default_factory=dict)
    notify_enabled: bool = False
    notify_first_minutes: float = 5
    notify_repeat_minutes: float = 15
    timeline_enabled: bool = True
    note_hotkey: str = ""

    def save(self) -> None:
        data = {
            "idle_timeout_seconds": self.idle_timeout_seconds,
            "poll_interval_seconds": self.poll_interval_seconds,
            "flush_interval_seconds": self.flush_interval_seconds,
            "autostart": self.autostart,
            "ignore_apps": self.ignore_apps,
            "file_rules": self.file_rules,
            "tags": self.tags,
            "tag_sort": self.tag_sort,
            "check_updates_on_startup": self.check_updates_on_startup,
            "backup_enabled": self.backup_enabled,
            "backup_dir": self.backup_dir,
            "backup_keep": self.backup_keep,
            "backup_interval_minutes": self.backup_interval_minutes,
            "app_colors": self.app_colors,
            "notify_enabled": self.notify_enabled,
            "notify_first_minutes": self.notify_first_minutes,
            "notify_repeat_minutes": self.notify_repeat_minutes,
            "timeline_enabled": self.timeline_enabled,
            "note_hotkey": self.note_hotkey,
        }
        tmp = CONFIG_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)
        os.replace(tmp, CONFIG_PATH)

    @property
    def merged_rules(self) -> dict[str, list[str]]:
        rules = dict(DEFAULT_FILE_RULES)
        rules.update(self.file_rules)
        return rules

    # -- tags -------------------------------------------------------------

    def tag_names(self) -> list[str]:
        return [t["name"] for t in self.tags]

    def _find_tag(self, name: str) -> dict | None:
        fold = (name or "").strip().casefold()
        for t in self.tags:
            if t.get("name", "").casefold() == fold:
                return t
        return None

    def tag_items(self, name: str) -> list[tuple[str, str | None]]:
        """The (app, file) items of one tag; `file` is None for a whole app."""
        tag = self._find_tag(name)
        if not tag:
            return []
        return [item_key(i.get("app", ""), i.get("file"))
                for i in tag.get("items", [])]

    def tags_for(self, app: str, file: str | None = None) -> list[str]:
        """Tags this exact item belongs to (an app row, or one file row)."""
        want = item_key(app, file)
        return [t["name"] for t in self.tags if want in self.tag_items(t["name"])]

    def create_tag(self, name: str) -> str:
        """Add an empty tag, returning the name it actually got.

        Names have to stay unique — a tag is addressed by name everywhere —
        so a clashing one is suffixed rather than silently merged.
        """
        base = (name or "").strip() or "New tag"
        candidate, n = base, 2
        while self._find_tag(candidate):
            candidate = f"{base} ({n})"
            n += 1
        self.tags.append({"name": candidate, "items": [], "created": _now()})
        return candidate

    def delete_tag(self, name: str) -> None:
        tag = self._find_tag(name)
        if tag:
            self.tags.remove(tag)

    def rename_tag(self, name: str, new_name: str) -> str:
        """Rename in place, returning the name used ('' if it wasn't possible)."""
        tag = self._find_tag(name)
        new = (new_name or "").strip()
        if not tag or not new:
            return ""
        clash = self._find_tag(new)
        if clash is not None and clash is not tag:
            return ""
        tag["name"] = new
        return new

    def set_item_tag(self, name: str, app: str, file: str | None,
                     on: bool) -> None:
        """Put an item in a tag, or take it out. Creates the tag if needed."""
        tag = self._find_tag(name)
        if tag is None:
            if not on:
                return
            self.create_tag(name)
            tag = self._find_tag(name)
            assert tag is not None
        key = item_key(app, file)
        items = tag.setdefault("items", [])
        kept = [i for i in items if item_key(i.get("app", ""), i.get("file")) != key]
        if on:
            # Stamped on the way in, so "what have I been filing lately" can
            # order the tag lists.
            kept.append(_item(key[0], key[1], _now()))
        tag["items"] = kept

    def tag_recency(self, name: str) -> int:
        """When this tag last gained an item (or was created, if never used)."""
        tag = self._find_tag(name)
        if not tag:
            return 0
        return max([_stamp(tag.get("created"))]
                   + [_stamp(i.get("added")) for i in tag.get("items", [])])

    def tag_order(self, sort: str | None = None) -> list[str]:
        """Tag names in display order. Ties keep the order they're stored in."""
        names = self.tag_names()
        if (sort or self.tag_sort) == BY_NAME:
            return sorted(names, key=lambda n: n.casefold())
        return sorted(names, key=lambda n: -self.tag_recency(n))

    def tracks_files(self, exe: str) -> bool:
        """Whether this app is currently split by file (vs. app-level only)."""
        return self.merged_rules.get(exe.lower()) != ["app"]

    def set_track_files(self, exe: str, track: bool) -> None:
        exe = exe.lower()
        if not track:
            self.file_rules[exe] = ["app"]
            return
        default = DEFAULT_FILE_RULES.get(exe)
        if default == ["app"]:
            # Its built-in behaviour is app-level; force generic detection.
            self.file_rules[exe] = ["auto"]
        else:
            # Fall back to the built-in pattern (or generic if none).
            self.file_rules.pop(exe, None)


def _backup_minutes(data: dict) -> int:
    """Backup interval in minutes, carrying over the old hours-based setting."""
    if "backup_interval_minutes" in data:
        value = data["backup_interval_minutes"]
    elif "backup_interval_hours" in data:          # written by <= 1.4.x
        value = float(data["backup_interval_hours"] or 0) * 60
    else:
        value = 30
    try:
        value = int(round(float(value)))
    except (TypeError, ValueError):
        return 30
    return max(1, min(value, 24 * 60))


def _tags_from(stored: dict) -> list[dict]:
    """Tags as stored, carrying over the app groups they replaced.

    <= 1.6 had "merges", which counted several exes as one app. A group makes
    a perfectly good tag — same name, its members as whole-app items — so an
    upgrade keeps the grouping as something the Tags view can still show.
    """
    if "tags" in stored:
        return clean_tags(stored["tags"])
    groups = stored.get("merges") or []
    carried = [{"name": g.get("name") or "Merged",
                "items": [{"app": m} for m in g.get("members", [])]}
               for g in groups if isinstance(g, dict)]
    return clean_tags(carried)


def load() -> Config:
    data = dict(DEFAULTS)
    stored: dict = {}          # only what the file actually said
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, encoding="utf-8") as fh:
                stored = json.load(fh)
            data.update(stored)
        except (json.JSONDecodeError, OSError):
            pass  # fall back to defaults on a corrupt config
    cfg = Config(
        idle_timeout_seconds=data.get("idle_timeout_seconds", 10),
        poll_interval_seconds=data.get("poll_interval_seconds", 1.0),
        flush_interval_seconds=data.get("flush_interval_seconds", 15),
        autostart=data.get("autostart", True),
        ignore_apps=[a.lower() for a in data.get("ignore_apps", [])],
        file_rules=data.get("file_rules", {}),
        # From `stored` for the same reason as the backup interval below: the
        # defaults carry an empty "tags", which would mask an older config.
        tags=_tags_from(stored),
        tag_sort=(data.get("tag_sort") if data.get("tag_sort") in
                  (BY_RECENT, BY_NAME) else BY_RECENT),
        check_updates_on_startup=data.get("check_updates_on_startup", True),
        backup_enabled=data.get("backup_enabled", True),
        backup_dir=data.get("backup_dir", ""),
        backup_keep=int(data.get("backup_keep", 7) or 7),
        # From `stored`, not `data`: the defaults already carry a minutes value,
        # which would mask an older config that only has the hours one.
        backup_interval_minutes=_backup_minutes(stored),
        app_colors=data.get("app_colors", {}),
        notify_enabled=bool(data.get("notify_enabled", False)),
        notify_first_minutes=data.get("notify_first_minutes", 5),
        notify_repeat_minutes=data.get("notify_repeat_minutes", 15),
        timeline_enabled=bool(data.get("timeline_enabled", True)),
        note_hotkey=str(data.get("note_hotkey") or ""),
    )
    return cfg


def friendly_name(exe: str) -> str:
    if not exe:
        return "Unknown"
    if exe in FRIENDLY_NAMES:
        return FRIENDLY_NAMES[exe]
    base = exe[:-4] if exe.endswith(".exe") else exe
    return base.replace("_", " ").replace("-", " ").title()


def parse_file(exe: str, title: str, rules: dict[str, list[str]]) -> str:
    """Extract the open file from a window title. '' means app-level only.

    Returns the fullest identity the title offers, so same-named files in
    different places stay distinct: a full path when the title shows one, else
    ``folder/file`` when the app names its project/workspace, else the bare
    filename (all a title like Photoshop's provides).
    """
    if not title:
        return ""
    patterns = rules.get(exe)
    if patterns == ["app"]:
        return ""
    if patterns == ["site"]:
        return parse_site(title)
    generic = [GENERIC_PATH_RE.pattern, GENERIC_FILE_RE.pattern]
    if patterns == ["auto"] or not patterns:
        use = generic
    else:
        use = patterns
    for pat in use:
        try:
            m = re.search(pat, title)
        except re.error:
            continue
        if not m or not m.groupdict().get("file"):
            continue
        name = _clean_token(m.group("file"))
        if not name:
            continue
        folder = _clean_token(m.groupdict().get("folder") or "")
        # Qualify with the project/workspace only when the file isn't already
        # a path (and the folder isn't just a repeat of the file name).
        if folder and not _has_dir(name) and folder != name:
            return f"{folder}/{name}"
        return name
    return ""


def _clean_token(value: str) -> str:
    """Trim whitespace and the unsaved/dirty markers editors prepend."""
    return value.strip().strip("*").strip().lstrip("●•*—- ").strip()


def _has_dir(value: str) -> bool:
    return "/" in value or "\\" in value
