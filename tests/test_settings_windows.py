"""The editor windows: Settings, Ignored apps, and Tags."""

import os
import types

import autostart
import config
import pytest
import updatedialog
import updater
from ignoreapps import IgnoreWindow
from tags import TagsWindow
from settings import SettingsWindow


@pytest.fixture(autouse=True)
def no_registry_writes(monkeypatch):
    """Never touch the real login-items registry/plist from a test."""
    monkeypatch.setattr(autostart, "set_enabled", lambda enabled: None)
    monkeypatch.setattr(autostart, "is_enabled", lambda: False)


@pytest.fixture
def settings(tk_root, cfg, store):
    tracker = types.SimpleNamespace(cfg=cfg)
    win = SettingsWindow(tk_root, cfg, tracker, storage=store)
    tk_root.update_idletasks()
    yield win
    try:
        win.close()
    except Exception:
        pass


def test_saves_intervals_and_toggles(settings, cfg, tk_root):
    settings.idle_var.set("25")
    settings.poll_var.set("0.5")
    settings.check_updates_var.set(False)
    settings.backup_var.set(False)
    settings._save()

    assert cfg.idle_timeout_seconds == 25
    assert cfg.poll_interval_seconds == 0.5
    assert cfg.check_updates_on_startup is False
    assert cfg.backup_enabled is False


def test_backup_interval_is_saved_in_minutes(settings, cfg):
    assert settings.backup_every_var.get() == "30", "default shown in the box"
    settings.backup_every_var.set("15")
    settings._save()
    assert cfg.backup_interval_minutes == 15


def test_a_silly_backup_interval_is_clamped(settings, cfg):
    settings.backup_every_var.set("0")
    settings._save()
    assert cfg.backup_interval_minutes == 1
    settings.backup_every_var.set("99999")
    settings._save()
    assert cfg.backup_interval_minutes == 1440


def test_out_of_range_values_are_clamped(settings, cfg):
    settings.idle_var.set("1")        # below the 2s minimum
    settings.poll_var.set("999")      # above the 10s maximum
    settings._save()
    assert cfg.idle_timeout_seconds == 2
    assert cfg.poll_interval_seconds == 10


def test_nonsense_input_is_rejected_without_saving(settings, cfg, monkeypatch):
    import tkinter.messagebox as mb
    shown = []
    monkeypatch.setattr(mb, "showerror", lambda *a, **k: shown.append(a))
    before = cfg.idle_timeout_seconds
    settings.idle_var.set("banana")
    settings._save()
    assert shown, "the user should be told the value is invalid"
    assert cfg.idle_timeout_seconds == before


def test_default_backup_dir_is_stored_as_empty(settings, cfg):
    """Storing "" keeps the default portable if the data dir ever moves."""
    settings.backup_path_var.set(os.path.join(config.APP_DIR, "backups"))
    settings._save()
    assert cfg.backup_dir == ""


def test_custom_backup_dir_is_kept(settings, cfg, tmp_path):
    settings.backup_path_var.set(str(tmp_path / "synced"))
    settings._save()
    assert cfg.backup_dir == str(tmp_path / "synced")


def test_backup_now_writes_a_file(settings, cfg, store, tmp_path, today, tk_root):
    store.add_seconds(today, "code.exe", "VS Code", "main.py", 10)
    settings.backup_path_var.set(str(tmp_path / "bk"))
    settings._backup_now()
    tk_root.update_idletasks()
    assert "Saved" in settings.backup_status.cget("text")
    assert (tmp_path / "bk" / f"data-{today}.db").exists()


def test_manual_update_check_shows_a_result(settings, tk_root, monkeypatch):
    shown = {}
    monkeypatch.setattr(updatedialog, "show_result",
                        lambda parent, res: shown.update(status=res.status))
    monkeypatch.setattr(updater, "check_async",
                        lambda cb, v=None: cb(updater.UpdateResult(
                            "update", latest="9.9.9")))
    settings._check_updates()
    for _ in range(5):
        tk_root.update(); tk_root.update_idletasks()
    assert shown.get("status") == "update"
    assert str(settings.update_btn.cget("state")) == "normal"


def test_about_section_credits_the_author(settings, tk_root):
    import settings as settings_mod
    texts = []

    def walk(widget):
        for child in widget.winfo_children():
            try:
                texts.append(str(child.cget("text")))
            except Exception:
                pass
            walk(child)

    walk(settings.win)
    blob = " ".join(texts)
    assert "Hau Tran" in blob and "Pixelmancer Studio" in blob
    assert settings_mod.AUTHOR_EMAIL in blob
    assert config.APP_VERSION in blob


def test_contact_link_opens_a_mail_draft(settings, monkeypatch):
    import settings as settings_mod
    import webbrowser
    opened = []
    monkeypatch.setattr(webbrowser, "open", lambda url: opened.append(url))
    settings._mail_author()
    assert opened == [f"mailto:{settings_mod.AUTHOR_EMAIL}"]


def test_contact_link_failure_is_not_fatal(settings, monkeypatch):
    import tkinter.messagebox as mb
    import webbrowser
    monkeypatch.setattr(webbrowser, "open",
                        lambda url: (_ for _ in ()).throw(OSError("no client")))
    shown = []
    monkeypatch.setattr(mb, "showinfo", lambda *a, **k: shown.append(a))
    settings._mail_author()          # must not raise
    assert shown


# --- ignored apps ----------------------------------------------------------

def test_ignore_window_add_and_remove(tk_root, store, today):
    store.add_seconds(today, "chrome.exe", "Chrome", "", 100)
    store.add_seconds(today, "game.exe", "Game", "", 200)
    cfg = config.Config(ignore_apps=["chrome.exe"])
    cfg.save = lambda: None  # type: ignore[method-assign]

    win = IgnoreWindow(tk_root, cfg, store)
    tk_root.update_idletasks()
    assert win.listbox.size() == 1
    assert all("chrome.exe" not in v for v in win.combo["values"]), \
        "already-ignored apps shouldn't be offered again"

    win.combo.set("game.exe")           # typed exe
    win._add()
    assert set(win.ignored) == {"chrome.exe", "game.exe"}

    win.listbox.selection_set(0)
    win._remove()
    win._save()
    assert cfg.ignore_apps == ["game.exe"]


# --- restore from backup ---------------------------------------------------

@pytest.fixture
def restore_win(tk_root, store, tmp_path, today):
    import backups
    from restore import RestoreWindow
    store.add_seconds(today, "code.exe", "VS Code", "main.py", 120)
    cfg = config.Config(backup_dir=str(tmp_path / "bk"))
    cfg.save = lambda: None  # type: ignore[method-assign]
    backups.run(store, cfg, today=today)          # one backup to choose from
    win = RestoreWindow(tk_root, cfg, store)
    tk_root.update_idletasks()
    yield win, cfg
    try:
        win.close()
    except Exception:
        pass


def test_restore_lists_available_backups(restore_win, today):
    win, _ = restore_win
    assert win.listbox.size() == 1
    assert today in win.listbox.get(0)


def test_selecting_a_backup_summarises_it_and_enables_the_actions(restore_win, today):
    win, _ = restore_win
    win.listbox.selection_set(0)
    win._on_pick()
    assert "2m 00s" in win.info.cget("text")       # the 120s we recorded
    assert str(win.merge_btn.cget("state")) == "normal"
    assert str(win.replace_btn.cget("state")) == "normal"


def test_selecting_junk_explains_and_keeps_the_actions_disabled(restore_win, tmp_path):
    win, _ = restore_win
    junk = tmp_path / "nope.db"
    junk.write_bytes(b"not a database")
    win._select(str(junk))
    assert "⚠" in win.info.cget("text")
    assert win.selected is None
    assert str(win.merge_btn.cget("state")) == "disabled"


def test_applying_a_restore_snapshots_first(restore_win, store, tmp_path,
                                            monkeypatch, today):
    import tkinter.messagebox as mb
    import backups
    import storage as storage_mod
    win, cfg = restore_win
    monkeypatch.setattr(mb, "askyesno", lambda *a, **k: True)
    monkeypatch.setattr(mb, "showinfo", lambda *a, **k: None)

    win.listbox.selection_set(0); win._on_pick()
    store.add_seconds(today, "later.exe", "Later", "", 90)   # not in the backup
    win._apply(storage_mod.REPLACE)

    # the replace happened …
    apps = {a["app"] for a in store.totals_by_app(today, today)}
    assert apps == {"code.exe"}
    # … and the pre-restore snapshot still holds what we discarded
    snaps = [n for n in os.listdir(backups.backup_dir(cfg))
             if n.startswith("pre-restore")]
    assert len(snaps) == 1
    undone = storage_mod.describe_backup(
        os.path.join(backups.backup_dir(cfg), snaps[0]))
    assert undone["seconds"] == 210, "the snapshot should hold the pre-restore total"


def test_declining_the_confirmation_changes_nothing(restore_win, store,
                                                    monkeypatch, today):
    import tkinter.messagebox as mb
    import storage as storage_mod
    win, _ = restore_win
    monkeypatch.setattr(mb, "askyesno", lambda *a, **k: False)

    store.add_seconds(today, "later.exe", "Later", "", 90)
    before = store.grand_total(today, today)
    win.listbox.selection_set(0); win._on_pick()
    win._apply(storage_mod.REPLACE)
    assert store.grand_total(today, today) == before


# --- tags ------------------------------------------------------------------

@pytest.fixture
def tagwin(tk_root, store, cfg, today):
    store.add_seconds(today, "code.exe", "VS Code", "main.py", 100)
    win = TagsWindow(tk_root, cfg, store)
    tk_root.update_idletasks()
    yield win
    try:
        win.close()
    except Exception:
        pass


def _item_rows(win):
    return win.items_inner.winfo_children()


def test_new_tag_is_created_and_selected(tagwin, tk_root, cfg, monkeypatch):
    import tags as tags_mod
    monkeypatch.setattr(tags_mod, "ask_tag_name", lambda *a, **k: "Work")
    tagwin._new_tag()
    tk_root.update_idletasks()

    assert cfg.tag_names() == ["Work"]
    assert tagwin.current == "Work"
    assert tagwin.taglist.get(0).startswith("Work")


def test_items_are_listed_with_a_remove_button(tagwin, tk_root, cfg):
    cfg.set_item_tag("Work", "code.exe", "main.py", True)
    cfg.set_item_tag("Work", "code.exe", None, True)
    tagwin._populate_tags(select="Work")
    tk_root.update_idletasks()

    labels = [w.winfo_children()[0].cget("text") for w in _item_rows(tagwin)]
    assert labels == ["main.py  ·  VS Code", "VS Code"]
    assert tagwin.taglist.get(0) == "Work  ·  2"

    tagwin._remove("code.exe", "main.py")
    tk_root.update_idletasks()
    assert cfg.tag_items("Work") == [("code.exe", None)]
    assert len(_item_rows(tagwin)) == 1


def test_sort_buttons_reorder_the_list_and_stick(tagwin, tk_root, cfg,
                                                 monkeypatch):
    clock = {"t": 100}
    monkeypatch.setattr(config, "_now", lambda: clock["t"])
    cfg.set_item_tag("Apple", "code.exe", None, True)
    clock["t"] = 200
    cfg.set_item_tag("Zebra", "code.exe", "main.py", True)
    tagwin._populate_tags(select=None)
    tk_root.update_idletasks()

    listed = lambda: [tagwin.taglist.get(i).split("  ·")[0]
                      for i in range(tagwin.taglist.size())]
    assert listed() == ["Zebra", "Apple"], "newest addition first by default"

    tagwin._set_sort(config.BY_NAME)
    tk_root.update_idletasks()
    assert listed() == ["Apple", "Zebra"]
    assert cfg.tag_sort == config.BY_NAME, "the choice is saved, not just applied"

    # …and the selection still points at the tag the row now holds
    tagwin.taglist.selection_clear(0, "end")
    tagwin.taglist.selection_set(0)
    tagwin._on_tag_select()
    assert tagwin.current == "Apple"


def test_deleting_a_tag_asks_first(tagwin, tk_root, cfg, monkeypatch):
    from tkinter import messagebox
    cfg.set_item_tag("Work", "code.exe", None, True)
    tagwin._populate_tags(select="Work")

    monkeypatch.setattr(messagebox, "askyesno", lambda *a, **k: False)
    tagwin._delete_tag()
    assert cfg.tag_names() == ["Work"]

    monkeypatch.setattr(messagebox, "askyesno", lambda *a, **k: True)
    tagwin._delete_tag()
    tk_root.update_idletasks()
    assert cfg.tag_names() == []
    assert tagwin.current is None


# --- timeline tab ------------------------------------------------------------

def test_settings_are_grouped_into_tabs(settings):
    tabs = [settings.tabs.tab(t, "text") for t in settings.tabs.tabs()]
    assert tabs == ["General", "Ignored apps", "Backup", "Timeline", "About"]


def test_timeline_is_on_and_hotkey_empty_by_default(settings):
    assert settings.timeline_var.get() is True
    assert settings.hotkey_var.get() == ""


def test_timeline_settings_are_saved(settings, cfg):
    settings.timeline_var.set(False)
    settings.hotkey_var.set("alt+ctrl+n")
    settings._save()
    assert cfg.timeline_enabled is False
    assert cfg.note_hotkey == "Ctrl+Alt+N"


def test_a_taken_hotkey_keeps_the_window_open(tk_root, cfg, store, monkeypatch):
    import tkinter.messagebox as mb
    warned = []
    monkeypatch.setattr(mb, "showwarning", lambda *a, **k: warned.append(a))
    applied = []
    win = SettingsWindow(tk_root, cfg, types.SimpleNamespace(cfg=cfg),
                         storage=store,
                         apply_hotkey=lambda spec: applied.append(spec) or False)
    win.hotkey_var.set("Ctrl+Alt+N")
    win._save()
    assert applied == ["Ctrl+Alt+N"] and warned
    assert cfg.note_hotkey == ""
    assert win.win.winfo_exists()
    win.close()


def test_the_hotkey_is_released_when_the_timeline_is_turned_off(tk_root, cfg, store):
    cfg.note_hotkey = "Ctrl+Alt+N"
    applied = []
    win = SettingsWindow(tk_root, cfg, types.SimpleNamespace(cfg=cfg),
                         storage=store,
                         apply_hotkey=lambda spec: applied.append(spec) or True)
    win.timeline_var.set(False)
    win._save()
    assert applied == [""]
    assert cfg.note_hotkey == "Ctrl+Alt+N", "remembered for when it's back on"


def test_hotkey_box_records_a_combination(settings):
    entry = settings.hotkey_entry

    def key(keysym, keycode=0):
        return types.SimpleNamespace(keysym=keysym, keycode=keycode)

    entry._on_focus_in()
    entry._on_key(key("Control_L"))
    entry._on_key(key("Shift_L"))
    assert entry._shown.get() == "Ctrl+Shift+…"
    entry._on_key(key("k"))
    assert settings.hotkey_var.get() == "Ctrl+Shift+K"

    entry._on_focus_in()
    entry._on_key(key("n"))                 # no modifier: not accepted
    assert settings.hotkey_var.get() == "Ctrl+Shift+K"
    entry._on_key(key("BackSpace"))
    assert settings.hotkey_var.get() == ""
