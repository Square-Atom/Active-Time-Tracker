"""Day timeline: recording blocks, notes, and turning them into a drawing."""

import datetime as dt
import time
import types

import hotkeys
import pytest
import storage as storage_mod
import timeline
from storage import ACTIVE, IDLE, UNTRACKED, Storage


def _at(day: str, hms: str) -> float:
    return dt.datetime.fromisoformat(f"{day}T{hms}").timestamp()


def _ticks(store, state, start, seconds, app="", name=""):
    """One-second ticks, the way the tracker records them."""
    for i in range(seconds):
        store.add_span(state, start + i, start + i + 1, app=app, app_name=name)


# --- storage: blocks ------------------------------------------------------

def test_contiguous_ticks_become_one_block(store, today):
    t0 = _at(today, "09:00:00")
    _ticks(store, ACTIVE, t0, 30, "code.exe", "VS Code")
    blocks = store.timeline_for_day(today)
    assert len(blocks) == 1
    assert blocks[0]["start"] == t0 and blocks[0]["end"] == t0 + 30
    assert blocks[0]["app"] == "code.exe"


def test_a_change_of_focus_starts_a_new_block(store, today):
    t0 = _at(today, "09:00:00")
    _ticks(store, ACTIVE, t0, 10, "code.exe", "VS Code")
    _ticks(store, IDLE, t0 + 10, 5)
    _ticks(store, ACTIVE, t0 + 15, 10, "code.exe", "VS Code")
    states = [(b["state"], b["app"]) for b in store.timeline_for_day(today)]
    assert states == [(ACTIVE, "code.exe"), (IDLE, ""), (ACTIVE, "code.exe")]


def test_a_gap_in_the_record_splits_a_block(store, today):
    t0 = _at(today, "09:00:00")
    _ticks(store, ACTIVE, t0, 10, "code.exe", "VS Code")
    _ticks(store, ACTIVE, t0 + 600, 10, "code.exe", "VS Code")   # app was closed
    blocks = store.timeline_for_day(today)
    assert [(b["start"], b["end"]) for b in blocks] == [
        (t0, t0 + 10), (t0 + 600, t0 + 610)]


def test_the_open_block_is_saved_and_then_updated_in_place(store, today):
    t0 = _at(today, "09:00:00")
    _ticks(store, ACTIVE, t0, 5, "a.exe", "A")
    store.flush()
    _ticks(store, ACTIVE, t0 + 5, 5, "a.exe", "A")
    store.flush()
    blocks = store.timeline_for_day(today)
    assert len(blocks) == 1 and blocks[0]["end"] == t0 + 10


def test_blocks_survive_a_restart(tmp_path, today):
    path = str(tmp_path / "data.db")
    s = Storage(path)
    t0 = _at(today, "09:00:00")
    _ticks(s, ACTIVE, t0, 5, "a.exe", "A")
    s.close()
    s = Storage(path)
    try:
        assert len(s.timeline_for_day(today)) == 1
        # Tracking again after the restart doesn't disturb the old block.
        _ticks(s, ACTIVE, t0 + 3600, 5, "a.exe", "A")
        assert len(s.timeline_for_day(today)) == 2
    finally:
        s.close()


def test_a_block_is_split_at_midnight(store):
    day = "2026-03-10"
    start = _at(day, "23:59:50")
    store.add_span(ACTIVE, start, start + 20, app="a.exe", app_name="A")
    first = store.timeline_for_day(day)
    second = store.timeline_for_day("2026-03-11")
    assert first[0]["end"] == _at("2026-03-11", "00:00:00")
    assert second[0]["start"] == _at("2026-03-11", "00:00:00")
    assert second[0]["end"] == start + 20


def test_restore_brings_back_timeline_and_notes(store, tmp_path, today):
    t0 = _at(today, "09:00:00")
    _ticks(store, ACTIVE, t0, 5, "a.exe", "A")
    store.save_note(f"{today} 09:00:03", "kept")
    backup = str(tmp_path / "backup.db")
    store.add_seconds(today, "a.exe", "A", "", 5)
    store.backup_to(backup)

    store.delete_note(f"{today} 09:00:03")
    store.restore_from(backup, storage_mod.REPLACE)
    assert len(store.timeline_for_day(today)) == 1
    assert store.notes_for_day(today) == {f"{today} 09:00:03": "kept"}


def test_merging_a_backup_keeps_current_notes(store, tmp_path, today):
    store.add_seconds(today, "a.exe", "A", "", 5)
    store.save_note(f"{today} 10:00:00", "old")
    backup = str(tmp_path / "backup.db")
    store.backup_to(backup)
    store.save_note(f"{today} 10:00:00", "new", replaces=f"{today} 10:00:00")
    store.restore_from(backup, storage_mod.MERGE)
    assert store.notes_for_day(today) == {f"{today} 10:00:00": "new"}


# --- storage: notes -------------------------------------------------------

def test_notes_are_listed_per_day_in_time_order(store, today):
    store.save_note(f"{today} 15:00:00", "later")
    store.save_note(f"{today} 09:30:00", "earlier")
    store.save_note("2020-01-01 09:00:00", "another day")
    assert list(store.notes_for_day(today).items()) == [
        (f"{today} 09:30:00", "earlier"), (f"{today} 15:00:00", "later")]


def test_editing_a_note_can_move_it(store, today):
    old = store.save_note(f"{today} 09:00:00", "draft")
    new = store.save_note(f"{today} 11:15:00", "final", replaces=old)
    assert store.notes_for_day(today) == {new: "final"}


def test_a_note_never_overwrites_another_at_the_same_second(store, today):
    first = store.save_note(f"{today} 09:00:00", "one")
    second = store.save_note(f"{today} 09:00:00", "two")
    assert first != second
    assert second == f"{today} 09:00:01"
    assert set(store.notes_for_day(today).values()) == {"one", "two"}


def test_deleting_a_note(store, today):
    ts = store.save_note(f"{today} 09:00:00", "bye")
    store.delete_note(ts)
    assert store.notes_for_day(today) == {}


# --- building blocks for display -----------------------------------------

def _seg(state, start, end, app="", name=""):
    return {"state": state, "start": start, "end": end, "app": app,
            "app_name": name}


def test_group_members_back_to_back_join_into_one_block():
    merge = {"godot.exe": ("merge::Godot", "Godot"),
             "godot_console.exe": ("merge::Godot", "Godot")}
    blocks = timeline.build_blocks([
        _seg(ACTIVE, 0, 10, "godot.exe", "Godot"),
        _seg(ACTIVE, 10, 20, "godot_console.exe", "Godot Console"),
    ], merge)
    assert len(blocks) == 1
    assert blocks[0]["key"] == "merge::Godot" and blocks[0]["end"] == 20


def test_ignored_apps_are_shown_without_their_name():
    blocks = timeline.build_blocks(
        [_seg(ACTIVE, 0, 10, "game.exe", "Game")], ignore={"game.exe"})
    assert blocks[0]["kind"] == "untracked"
    assert "Game" not in blocks[0]["name"]


def test_idle_and_untracked_are_their_own_kinds():
    blocks = timeline.build_blocks([_seg(IDLE, 0, 5), _seg(UNTRACKED, 5, 9)])
    assert [b["kind"] for b in blocks] == ["idle", "untracked"]


def test_today_runs_to_now_and_past_days_to_their_last_block():
    blocks = [{"start": 100.0, "end": 5000.0}]
    assert timeline.view_bounds(blocks, [], True, 9000.0) == (100.0, 9000.0)
    assert timeline.view_bounds(blocks, [], False, 9000.0) == (100.0, 5000.0)


def test_notes_widen_the_view_and_an_empty_day_has_none():
    blocks = [{"start": 1000.0, "end": 5000.0}]
    assert timeline.view_bounds(blocks, [200.0], False, 0) == (200.0, 5000.0)
    assert timeline.view_bounds([], [], True, 0) is None


def test_a_tiny_span_is_padded_to_a_readable_width():
    start, end = timeline.view_bounds([{"start": 0.0, "end": 5.0}], [], False, 0)
    assert end - start == timeline.MIN_SPAN


@pytest.mark.parametrize("span_h,width,step", [
    (10, 1000, 60), (10, 300, 180), (1, 1000, 5), (24, 400, 240),
])
def test_tick_spacing_leaves_room_for_labels(span_h, width, step):
    assert timeline.tick_step_minutes(span_h * 3600, width) == step


# --- hotkeys --------------------------------------------------------------

@pytest.mark.parametrize("spec,expected", [
    ("Ctrl+Alt+N", "Ctrl+Alt+N"),
    ("alt + control + n", "Ctrl+Alt+N"),
    ("shift+win+f5", "Shift+Win+F5"),
    ("F9", "F9"),                      # a function key may stand alone
    ("Ctrl+pageup", "Ctrl+PageUp"),
    ("N", ""),                         # would fire while typing
    ("Ctrl+Alt", ""),                  # no key
    ("Ctrl+Foo", ""),
    ("", ""),
])
def test_hotkey_spelling_is_normalised(spec, expected):
    assert hotkeys.normalize(spec) == expected


def test_tk_keys_map_to_hotkey_names():
    assert hotkeys.key_from_tk("n") == "N"
    assert hotkeys.key_from_tk("Prior") == "PageUp"
    assert hotkeys.key_from_tk("F12") == "F12"
    assert hotkeys.key_from_tk("Control_L") is None
    assert hotkeys.modifier_for_keysym("Control_L") == "Ctrl"


def test_hotkey_manager_registers_and_swaps(monkeypatch):
    import sysinfo
    live = []

    class Handle:
        def __init__(self, spec):
            self.spec = spec
            live.append(spec)

        def stop(self):
            live.remove(self.spec)

    def register(mods, key, callback):
        spec = hotkeys.format_spec(mods, key)
        return None if spec == "Ctrl+Alt+T" else Handle(spec)

    monkeypatch.setattr(sysinfo, "register_hotkey", register)
    mgr = hotkeys.HotkeyManager(lambda: None)
    assert mgr.set("ctrl+alt+n") and live == ["Ctrl+Alt+N"]
    assert mgr.set("Ctrl+Shift+N") and live == ["Ctrl+Shift+N"]
    assert not mgr.set("Ctrl+Alt+T"), "taken by another app"
    assert live == [] and mgr.spec == ""
    assert mgr.set("") and live == []


# --- tracker --------------------------------------------------------------

def test_the_tracker_records_focus_and_idle_blocks(store, monkeypatch, today):
    import config
    import sysinfo
    import tracker as tracker_mod

    idle = {"seconds": 0.0}
    monkeypatch.setattr(sysinfo, "get_idle_seconds", lambda: idle["seconds"])
    monkeypatch.setattr(sysinfo, "get_foreground_window",
                        lambda: sysinfo.WindowInfo(1, "a.py - p - Visual Studio Code",
                                                   "code.exe", 4321))
    cfg = config.Config(poll_interval_seconds=0.1, flush_interval_seconds=0.2)
    cfg.save = lambda: None
    tr = tracker_mod.Tracker(store, cfg)
    tr.start()
    time.sleep(0.5)
    idle["seconds"] = 999
    time.sleep(0.5)
    tr.stop()

    blocks = store.timeline_for_day(today)
    assert [(b["state"], b["app"]) for b in blocks] == [
        (ACTIVE, "code.exe"), (IDLE, "")]
    assert blocks[0]["end"] == pytest.approx(blocks[1]["start"], abs=0.05)


# --- the view -------------------------------------------------------------

@pytest.fixture
def view(tk_root, store):
    theme = {"bg": "#000000", "panel": "#111111", "fg": "#ffffff",
             "muted": "#888888", "accent": "#7c9cff", "hover": "#222222"}
    v = timeline.TimelineView(tk_root, store, theme, color_for=lambda k: "#ff0000")
    v.pack(fill="x")
    tk_root.geometry("900x200")
    tk_root.deiconify()
    tk_root.update()
    yield v
    v.close_popups()
    tk_root.withdraw()


def test_view_draws_blocks_and_notes(view, store, today):
    t0 = _at(today, "09:00:00")
    _ticks(store, ACTIVE, t0, 60, "a.exe", "A")
    _ticks(store, IDLE, t0 + 60, 30)
    store.save_note(f"{today} 09:00:30", "hello")
    view.load(dt.date.today())
    view.update()
    fills = {view.canvas.itemcget(i, "fill") for i in view.canvas.find_all()}
    assert "#ff0000" in fills and timeline.IDLE_COLOR in fills
    assert timeline.NOTE_PAPER in fills
    assert [ts for _, ts in view._note_hits] == [f"{today} 09:00:30"]


def test_clicking_a_note_offers_edit_and_delete(view, store, today, monkeypatch):
    _ticks(store, ACTIVE, _at(today, "09:00:00"), 60, "a.exe", "A")
    ts = store.save_note(f"{today} 09:00:30", "hello")
    view.load(dt.date.today())
    view.update()
    x = view._note_hits[0][0]
    view._on_click(types.SimpleNamespace(x=x, y=10))
    assert set(view._actions.buttons) == {"edit", "delete"}

    monkeypatch.setattr(timeline.messagebox, "askyesno", lambda *a, **k: True)
    view._delete(ts)
    assert store.notes_for_day(today) == {}
    assert view._actions is None and view._note_hits == []


def test_editing_a_note_saves_the_new_text(view, store, today, monkeypatch):
    ts = store.save_note(f"{today} 09:00:30", "hello")
    view.load(dt.date.today())
    monkeypatch.setattr(timeline, "ask_note",
                        lambda *a, **k: (f"{today} 10:00:00", "edited"))
    view._edit_existing(ts)
    assert store.notes_for_day(today) == {f"{today} 10:00:00": "edited"}


def test_an_empty_day_says_so(view):
    view.load(dt.date(2001, 1, 1))
    view.update()
    texts = [view.canvas.itemcget(i, "text") for i in view.canvas.find_all()
             if view.canvas.type(i) == "text"]
    assert any("No timeline" in t for t in texts)
