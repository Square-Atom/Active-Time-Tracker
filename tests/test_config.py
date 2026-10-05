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


# --- folders (file managers) ----------------------------------------------

@pytest.mark.parametrize("exe,title,expected", [
    ("explorer.exe", "Documents", "Documents"),                     # Windows 10
    ("explorer.exe", "Documents - File Explorer", "Documents"),     # Windows 11
    ("explorer.exe", "Downloads and 2 more tabs - File Explorer", "Downloads"),
    ("explorer.exe", "Downloads and 1 more tab - File Explorer", "Downloads"),
    # "Display the full path in the title bar" is on
    ("explorer.exe", r"C:\Users\hau\Art - Old - File Explorer", r"C:\Users\hau\Art - Old"),
    ("explorer.exe", "This PC - File Explorer", "This PC"),
    ("explorer.exe", "Program Manager", ""),                       # the desktop
    ("explorer.exe", "", ""),                                      # the taskbar
    ("finder", "Downloads", "Downloads"),
    ("nautilus", "Pictures", "Pictures"),
    ("dolphin", "Music — Dolphin", "Music"),
    ("dolphin", "/home/hau/Music - Old — Dolphin", "/home/hau/Music - Old"),
    ("thunar", "Documents - File Manager", "Documents"),
    ("thunar", "Documents - Thunar", "Documents"),
    ("nemo", "Projects - Old", "Projects - Old"),       # no branding to strip
])
def test_parse_folder(exe, title, expected):
    assert parse(exe, title) == expected


def test_only_the_file_managers_own_branding_is_stripped():
    # A folder that happens to end in another app's name keeps it.
    assert parse("nautilus", "Notes - Dolphin") == "Notes - Dolphin"
    assert parse("explorer.exe", "Notes - Files") == "Notes - Files"


# --- per-app tracking toggle ----------------------------------------------

def test_track_files_toggle_round_trip(cfg):
    assert cfg.tracks_files("photoshop.exe") is True
    assert cfg.tracks_files("chrome.exe") is True      # browsers -> site
    assert cfg.tracks_files("explorer.exe") is True    # file managers -> folder

    cfg.set_track_files("chrome.exe", False)
    assert cfg.file_rules["chrome.exe"] == ["app"]
    assert config.parse_file("chrome.exe", "GitHub - Google Chrome",
                             cfg.merged_rules) == ""

    cfg.set_track_files("chrome.exe", True)
    assert "chrome.exe" not in cfg.file_rules          # back to built-in
    assert config.parse_file("chrome.exe", "GitHub - Google Chrome",
                             cfg.merged_rules) == "GitHub"


def test_enabling_an_app_level_app_forces_generic_detection(cfg):
    cfg.set_track_files("cmd.exe", False)
    cfg.set_track_files("cmd.exe", True)
    assert "cmd.exe" not in cfg.file_rules             # no built-in rule: generic
    config.DEFAULT_FILE_RULES["fake.exe"] = ["app"]
    try:
        cfg.set_track_files("fake.exe", True)
        assert cfg.file_rules["fake.exe"] == ["auto"]
    finally:
        del config.DEFAULT_FILE_RULES["fake.exe"]


def test_folder_tracking_toggles_off_and_back_on(cfg):
    cfg.set_track_files("explorer.exe", False)
    assert parse_with(cfg, "explorer.exe", "Documents - File Explorer") == ""
    cfg.set_track_files("explorer.exe", True)
    assert "explorer.exe" not in cfg.file_rules        # back to folder tracking
    assert parse_with(cfg, "explorer.exe", "Documents - File Explorer") == "Documents"


def parse_with(cfg, exe, title):
    return config.parse_file(exe, title, cfg.merged_rules)


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


def test_a_tag_sits_in_one_group_at_a_time():
    cfg = config.Config()
    cfg.create_tag("Work")
    assert cfg.create_group("Projects") == "Projects"
    assert cfg.create_group("projects") == "projects (2)", "names stay unique"
    cfg.set_tag_group("Work", "Projects")
    cfg.set_tag_group("Work", "projects (2)")
    assert cfg.tag_group("Work") == "projects (2)"
    assert cfg.group_tags("Projects") == []

    cfg.set_tag_group("Work", "No such group")     # same as taking it out
    assert cfg.tag_group("Work") == ""
    assert cfg.group_tags("") == ["Work"]


def test_renaming_and_deleting_a_group_carry_its_tags():
    cfg = config.Config()
    cfg.create_tag("Work")
    cfg.create_tag("Play")
    cfg.create_group("Projects")
    cfg.create_group("Other")
    cfg.set_tag_group("Work", "Projects")

    assert cfg.rename_group("Projects", "Other") == "", "a clash is refused"
    assert cfg.rename_group("Projects", "Clients") == "Clients"
    assert cfg.tag_group("Work") == "Clients"

    cfg.rename_tag("Work", "Job")                   # the tag keeps its group
    assert cfg.group_tags("Clients") == ["Job"]

    cfg.delete_group("Clients")
    assert cfg.tag_groups == ["Other"]
    assert cfg.tag_group("Job") == ""
    assert sorted(cfg.tag_names()) == ["Job", "Play"]


def test_groups_survive_a_save_and_drop_what_they_cannot_place(tmp_path,
                                                               monkeypatch):
    monkeypatch.setattr(config, "CONFIG_PATH", str(tmp_path / "config.json"))
    cfg = config.Config()
    cfg.create_tag("Work")
    cfg.create_tag("Stray")
    cfg.create_group("Projects")
    cfg.create_group("Empty")
    cfg.set_tag_group("Work", "Projects")
    cfg.tags[1]["group"] = "Gone"                   # a group nobody lists
    cfg.save()

    loaded = config.load()
    assert loaded.tag_groups == ["Projects", "Empty"], "an empty group is kept"
    assert loaded.tag_group("Work") == "Projects"
    assert loaded.tag_group("Stray") == ""


def test_tags_can_be_ordered_by_recent_addition_or_by_name(monkeypatch):
    clock = {"t": 100}
    monkeypatch.setattr(config, "_now", lambda: clock["t"])
    cfg = config.Config()
    cfg.set_item_tag("Apple", "a.exe", None, True)
    clock["t"] = 200
    cfg.set_item_tag("Zebra", "z.exe", None, True)

    assert cfg.tag_order(config.BY_RECENT) == ["Zebra", "Apple"]
    assert cfg.tag_order(config.BY_NAME) == ["Apple", "Zebra"]

    clock["t"] = 300                       # Apple gains something newer
    cfg.set_item_tag("Apple", "b.exe", None, True)
    assert cfg.tag_order(config.BY_RECENT) == ["Apple", "Zebra"]


def test_a_brand_new_tag_counts_as_the_most_recent(monkeypatch):
    """Otherwise the tag you just made would land at the bottom of the list."""
    clock = {"t": 100}
    monkeypatch.setattr(config, "_now", lambda: clock["t"])
    cfg = config.Config()
    cfg.set_item_tag("Old", "a.exe", None, True)
    clock["t"] = 200
    cfg.create_tag("Empty")
    assert cfg.tag_order(config.BY_RECENT) == ["Empty", "Old"]


def test_untimed_tags_keep_the_order_they_are_stored_in():
    """Tags carried over from app groups have no timestamps at all."""
    cfg = config.Config(tags=config.clean_tags([
        {"name": "First", "items": [{"app": "a.exe"}]},
        {"name": "Second", "items": [{"app": "b.exe"}]}]))
    assert cfg.tag_order(config.BY_RECENT) == ["First", "Second"]


def test_the_sort_choice_is_remembered(tmp_path, monkeypatch):
    import json
    path = tmp_path / "config.json"
    monkeypatch.setattr(config, "CONFIG_PATH", str(path))
    cfg = config.load()
    assert cfg.tag_sort == config.BY_RECENT      # the default
    cfg.tag_sort = config.BY_NAME
    cfg.save()
    assert config.load().tag_sort == config.BY_NAME

    path.write_text(json.dumps({"tag_sort": "nonsense"}), encoding="utf-8")
    assert config.load().tag_sort == config.BY_RECENT


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


def test_an_old_track_files_override_does_not_block_folders(tmp_path, monkeypatch):
    """<= 1.8 saved ["auto"] when File Explorer's "Track files" was ticked;
    that now means "track folders". An explicit ["app"] is left alone."""
    import json
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"file_rules": {"explorer.exe": ["auto"],
                                               "nautilus": ["app"],
                                               "code.exe": ["auto"]}}))
    monkeypatch.setattr(config, "CONFIG_PATH", str(path))
    cfg = config.load()
    assert "explorer.exe" not in cfg.file_rules
    assert cfg.merged_rules["explorer.exe"] == ["folder"]
    assert cfg.file_rules["nautilus"] == ["app"]
    assert cfg.file_rules["code.exe"] == ["auto"]
