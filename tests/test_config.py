"""Window-title parsing: files, paths, project folders, and websites."""

import config
import pytest

RULES = config.Config().merged_rules


def parse(exe, title):
    return config.parse_file(exe, title, RULES)


# --- files -----------------------------------------------------------------

@pytest.mark.parametrize("exe,title,expected", [
    ("code.exe", "● main.py - myproject - Visual Studio Code", "myproject/main.py"),
    ("code.exe", "dashboard.py - Work-Time-Tracker - Visual Studio Code",
     "Work-Time-Tracker/dashboard.py"),   # hyphenated folder stays intact
    ("devenv.exe", "Program.cs - MySolution - Microsoft Visual Studio",
     "MySolution/Program.cs"),
    ("obsidian.exe", "Daily note - MyVault - Obsidian", "MyVault/Daily note"),
    ("pyxeledit.exe", "Pyxel Edit - hero_sheet.pyxel *", "hero_sheet.pyxel"),
    ("aseprite.exe", "Aseprite v1.3 - goblin.aseprite", "goblin.aseprite"),
    ("photoshop.exe", "poster.psd @ 66.7% (Layer 1, RGB/8) *", "poster.psd"),
    ("blender.exe", "Blender - scene.blend", "scene.blend"),
    ("notepad.exe", "*notes.txt - Notepad", "notes.txt"),
    ("winword.exe", "Report Q3 - Word", "Report Q3"),
    ("unknownapp.exe", "render.exr - MyTool", "render.exr"),   # generic fallback
    ("unknownapp.exe", "Untitled document", ""),               # no file at all
    ("explorer.exe", "Documents", ""),                         # app-level only
])
def test_parse_file(exe, title, expected):
    assert parse(exe, title) == expected


@pytest.mark.parametrize("exe,title,expected", [
    ("notepad++.exe", r"C:\work\a\design.psd - Notepad++", r"C:\work\a\design.psd"),
    ("unknownapp.exe", r"editing C:\data\sheet.csv now", r"C:\data\sheet.csv"),
])
def test_full_paths_win(exe, title, expected):
    assert parse(exe, title) == expected


def test_same_name_files_stay_distinct():
    """The bug this was written for: two design.psd in different folders."""
    a = parse("code.exe", "design.py - ProjectA - Visual Studio Code")
    b = parse("code.exe", "design.py - ProjectB - Visual Studio Code")
    assert a != b == "ProjectB/design.py"


# --- websites --------------------------------------------------------------

@pytest.mark.parametrize("title,expected", [
    ("Facebook - Google Chrome", "Facebook"),
    ("(3) Facebook - Google Chrome", "Facebook"),          # unread counter
    ("Never Gonna Give You Up - YouTube - Google Chrome", "YouTube"),
    ("GitHub - torvalds/linux: kernel tree - Google Chrome", "GitHub"),  # site first
    ("How do I parse? - Stack Overflow - Google Chrome", "Stack Overflow"),
    ("Inbox (12) - me@gmail.com - Gmail - Google Chrome", "Gmail"),
    ("Home / X - Google Chrome", "X"),
    ("Best pizza : r/cooking - Google Chrome", "Reddit"),
    ("Some Article - My Cool Blog - Google Chrome", "My Cool Blog"),  # unknown site
    ("Google Chrome", ""),                                  # branding only
    ("", ""),
])
def test_parse_site_chrome(title, expected):
    assert parse("chrome.exe", title) == expected


@pytest.mark.parametrize("exe,title,expected", [
    ("firefox.exe", "Facebook — Mozilla Firefox", "Facebook"),
    ("msedge.exe", "YouTube and 4 more pages - Personal - Microsoft\u200b Edge",
     "YouTube"),
    ("msedge.exe", "GitHub - Personal - Microsoft Edge", "GitHub"),
    ("brave.exe", "Twitch - Brave", "Twitch"),
])
def test_parse_site_other_browsers(exe, title, expected):
    assert parse(exe, title) == expected


def test_edge_profile_allowance_is_not_global():
    """Regression: allowing Edge's profile segment for every browser swallowed
    the real site in "… - YouTube - Google Chrome"."""
    assert parse("chrome.exe", "Video - YouTube - Google Chrome") == "YouTube"


def test_long_site_is_truncated():
    site = parse("chrome.exe", "X" * 90 + " - Google Chrome")
    assert 0 < len(site) <= 40


# --- per-app tracking toggle ----------------------------------------------

def test_track_files_toggle_round_trip(cfg):
    assert cfg.tracks_files("photoshop.exe") is True
    assert cfg.tracks_files("chrome.exe") is True      # browsers -> site
    assert cfg.tracks_files("explorer.exe") is False   # app-level default

    cfg.set_track_files("chrome.exe", False)
    assert cfg.file_rules["chrome.exe"] == ["app"]
    assert config.parse_file("chrome.exe", "GitHub - Google Chrome",
                             cfg.merged_rules) == ""

    cfg.set_track_files("chrome.exe", True)
    assert "chrome.exe" not in cfg.file_rules          # back to built-in
    assert config.parse_file("chrome.exe", "GitHub - Google Chrome",
                             cfg.merged_rules) == "GitHub"


def test_enabling_an_app_level_app_forces_generic_detection(cfg):
    cfg.set_track_files("explorer.exe", True)
    assert cfg.file_rules["explorer.exe"] == ["auto"]


def test_friendly_names():
    assert config.friendly_name("pyxeledit.exe") == "Pyxel Edit"
    assert config.friendly_name("activetimetracker.exe") == "Active Time Tracker"
    assert config.friendly_name("randomtool.exe") == "Randomtool"


def test_invalid_user_regex_is_ignored_not_raised():
    rules = dict(RULES, **{"mytool.exe": ["(?P<file>["]})   # unbalanced bracket
    assert config.parse_file("mytool.exe", "whatever.txt", rules) == ""


# --- merges ----------------------------------------------------------------

def test_merge_map_and_members():
    cfg = config.Config(merges=[
        {"name": "Godot", "members": ["godot.exe", "godot_console.exe"]}])
    assert cfg.merge_map()["godot.exe"] == ("merge::Godot", "Godot")
    assert set(cfg.group_members()["merge::Godot"]) == {
        "godot.exe", "godot_console.exe"}
