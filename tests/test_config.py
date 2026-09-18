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


@pytest.mark.parametrize("exe,title,expected", [
    # Hyphens are the tricky case: a bare "-" used to be treated as a separator,
    # so "clockwork-workshop.pyxel" was truncated to "workshop.pyxel".
    ("pyxeledit.exe", "Pyxel Edit - clockwork-workshop.pyxel",
     "clockwork-workshop.pyxel"),
    ("pyxeledit.exe", "Pyxel Edit - clockwork_workshop.pyxel",
     "clockwork_workshop.pyxel"),
    ("pyxeledit.exe", "Pyxel Edit - clockwork workshop.pyxel",
     "clockwork workshop.pyxel"),
    ("pyxeledit.exe", "Pyxel Edit - my-tile-set_v2 final.pyxel",
     "my-tile-set_v2 final.pyxel"),
    ("aseprite.exe", "Aseprite v1.3 - goblin-king.aseprite", "goblin-king.aseprite"),
    ("photoshop.exe", "poster-final-v2.psd @ 66.7% (Layer 1, RGB/8) *",
     "poster-final-v2.psd"),
    ("blender.exe", "Blender - space-ship_01.blend", "space-ship_01.blend"),
    ("unknownapp.exe", "MyTool - some-render_01.exr", "some-render_01.exr"),
])
def test_punctuation_in_filenames_survives(exe, title, expected):
    assert parse(exe, title) == expected


def test_app_name_prefix_is_still_stripped():
    """The separator fix must not stop us trimming the app name."""
    assert parse("pyxeledit.exe", "Pyxel Edit - hero.pyxel") == "hero.pyxel"
    assert parse("krita.exe", "Krita - [C:/art/my-piece.kra]") == "C:/art/my-piece.kra"


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


# --- tags ------------------------------------------------------------------

def test_an_item_can_be_an_app_or_one_file_inside_it():
    cfg = config.Config()
    cfg.create_tag("Work")
    cfg.set_item_tag("Work", "Code.exe", None, True)        # the whole app
    cfg.set_item_tag("Work", "chrome.exe", "GitHub", True)  # one site
    assert cfg.tag_items("Work") == [("code.exe", None), ("chrome.exe", "GitHub")]
    # the app entry and the file entry are different items, not the same one
    assert cfg.tags_for("code.exe") == ["Work"]
    assert cfg.tags_for("code.exe", "main.py") == []
    assert cfg.tags_for("chrome.exe", "GitHub") == ["Work"]


def test_one_item_can_carry_several_tags():
    cfg = config.Config()
    cfg.set_item_tag("Work", "code.exe", "main.py", True)   # creates the tag
    cfg.set_item_tag("Side project", "code.exe", "main.py", True)
    assert cfg.tags_for("code.exe", "main.py") == ["Work", "Side project"]

    cfg.set_item_tag("Work", "code.exe", "main.py", False)
    assert cfg.tags_for("code.exe", "main.py") == ["Side project"]


def test_tagging_the_same_item_twice_does_not_duplicate_it():
    cfg = config.Config()
    cfg.set_item_tag("Work", "code.exe", None, True)
    cfg.set_item_tag("Work", "CODE.exe", None, True)
    assert cfg.tag_items("Work") == [("code.exe", None)]


def test_tag_names_stay_unique():
    cfg = config.Config()
    assert cfg.create_tag("Work") == "Work"
    assert cfg.create_tag("Work") == "Work (2)"
    assert cfg.rename_tag("Work (2)", "Work") == "", "a clash is refused"
    assert cfg.rename_tag("Work (2)", "Play") == "Play"
    assert cfg.tag_names() == ["Work", "Play"]


def test_deleting_a_tag_leaves_the_others_alone():
    cfg = config.Config()
    cfg.set_item_tag("Work", "code.exe", None, True)
    cfg.set_item_tag("Play", "game.exe", None, True)
    cfg.delete_tag("Work")
    assert cfg.tag_names() == ["Play"]


def test_unusable_tags_are_dropped_when_loaded():
    tags = config.clean_tags([
        {"name": "  Work  ", "items": [{"app": "Code.exe"}, "game.exe", {}]},
        {"name": "", "items": []},          # nameless: dropped
        {"name": "work", "items": []},      # duplicate name: dropped
        "nonsense",
    ])
    assert [t["name"] for t in tags] == ["Work"]
    assert tags[0]["items"] == [{"app": "code.exe"}, {"app": "game.exe"}]


def test_app_groups_are_carried_over_as_tags(tmp_path, monkeypatch):
    """<= 1.6 config: a group becomes a tag holding the same apps."""
    import json
    path = tmp_path / "config.json"
    path.write_text(json.dumps({
        "merges": [{"name": "Godot", "members": ["godot.exe", "godot_console.exe"]}]
    }), encoding="utf-8")
    monkeypatch.setattr(config, "CONFIG_PATH", str(path))
    cfg = config.load()
    assert cfg.tags == [{"name": "Godot", "items": [{"app": "godot.exe"},
                                                    {"app": "godot_console.exe"}]}]
