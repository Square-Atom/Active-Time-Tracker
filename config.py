"""Configuration: paths, defaults, friendly names, and title-parsing rules.

Config lives in a per-user data directory (see `_data_dir`) as config.json, so it
survives code updates. Users can edit the JSON to add/adjust file-parsing rules.
"""

from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import dataclass, field

APP_NAME = "ActiveTimeTracker"
APP_VERSION = "1.2.0"  # keep in sync with the git tag used for releases
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
    # Groups of exes counted as one app in reports (non-destructive, applied at
    # read time), e.g. [{"name": "Godot", "members": ["godot.exe", "godot_console.exe"]}]
    "merges": [],
    "check_updates_on_startup": True,
    # Daily rotating backups of data.db (+ config.json).
    "backup_enabled": True,
    "backup_dir": "",      # "" = <data dir>/backups; set a synced folder for
                           # off-machine safety (OneDrive, Nextcloud, …)
    "backup_keep": 7,
}

MERGE_PREFIX = "merge::"  # synthetic app key for a merged group


@dataclass
class Config:
    idle_timeout_seconds: float = 10
    poll_interval_seconds: float = 1.0
    flush_interval_seconds: float = 15
    autostart: bool = True
    ignore_apps: list[str] = field(default_factory=list)
    file_rules: dict[str, list[str]] = field(default_factory=dict)
    merges: list[dict] = field(default_factory=list)
    check_updates_on_startup: bool = True
    backup_enabled: bool = True
    backup_dir: str = ""
    backup_keep: int = 7

    def save(self) -> None:
        data = {
            "idle_timeout_seconds": self.idle_timeout_seconds,
            "poll_interval_seconds": self.poll_interval_seconds,
            "flush_interval_seconds": self.flush_interval_seconds,
            "autostart": self.autostart,
            "ignore_apps": self.ignore_apps,
            "file_rules": self.file_rules,
            "merges": self.merges,
            "check_updates_on_startup": self.check_updates_on_startup,
            "backup_enabled": self.backup_enabled,
            "backup_dir": self.backup_dir,
            "backup_keep": self.backup_keep,
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

    def merge_map(self) -> dict[str, tuple[str, str]]:
        """member_exe -> (group_key, group_name) for read-time app merging."""
        out: dict[str, tuple[str, str]] = {}
        for g in self.merges:
            name = (g.get("name") or "Merged").strip() or "Merged"
            key = MERGE_PREFIX + name
            for member in g.get("members", []):
                m = member.strip().lower()
                if m:
                    out[m] = (key, name)
        return out

    def group_members(self) -> dict[str, list[str]]:
        """group_key -> [member exes]."""
        out: dict[str, list[str]] = {}
        for g in self.merges:
            name = (g.get("name") or "Merged").strip() or "Merged"
            key = MERGE_PREFIX + name
            members = [m.strip().lower() for m in g.get("members", []) if m.strip()]
            out.setdefault(key, []).extend(members)
        return out

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


def load() -> Config:
    data = dict(DEFAULTS)
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, encoding="utf-8") as fh:
                data.update(json.load(fh))
        except (json.JSONDecodeError, OSError):
            pass  # fall back to defaults on a corrupt config
    cfg = Config(
        idle_timeout_seconds=data.get("idle_timeout_seconds", 10),
        poll_interval_seconds=data.get("poll_interval_seconds", 1.0),
        flush_interval_seconds=data.get("flush_interval_seconds", 15),
        autostart=data.get("autostart", True),
        ignore_apps=[a.lower() for a in data.get("ignore_apps", [])],
        file_rules=data.get("file_rules", {}),
        merges=data.get("merges", []),
        check_updates_on_startup=data.get("check_updates_on_startup", True),
        backup_enabled=data.get("backup_enabled", True),
        backup_dir=data.get("backup_dir", ""),
        backup_keep=int(data.get("backup_keep", 7) or 7),
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
