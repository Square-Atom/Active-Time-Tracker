"""Dashboard: date ranges (pure logic) and rendering (needs a display)."""

import datetime as dt
import types

import config
import pytest
from dashboard import Dashboard, RangeState, fmt_duration


# --- pure logic ------------------------------------------------------------

@pytest.mark.parametrize("seconds,text", [
    (0, "0s"), (45, "45s"), (90, "1m 30s"), (3600, "1h 00m"), (5400, "1h 30m"),
])
def test_fmt_duration(seconds, text):
    assert fmt_duration(seconds) == text


def test_day_range():
    r = RangeState()
    r.anchor = dt.date(2026, 8, 10)
    assert r.bounds() == ("2026-08-10", "2026-08-10")
    assert r.is_multiday is False


def test_week_starts_monday():
    r = RangeState(); r.mode = "week"
    r.anchor = dt.date(2026, 8, 12)          # a Wednesday
    assert r.bounds() == ("2026-08-10", "2026-08-16")


def test_month_covers_whole_month():
    r = RangeState(); r.mode = "month"
    r.anchor = dt.date(2026, 2, 15)
    assert r.bounds() == ("2026-02-01", "2026-02-28")


def test_year_range_and_paging():
    r = RangeState(); r.mode = "year"
    r.anchor = dt.date(2026, 8, 10)
    assert r.bounds() == ("2026-01-01", "2026-12-31")
    assert r.label() == "2026"
    r.shift(-1)
    assert r.bounds() == ("2025-01-01", "2025-12-31")


def test_custom_range_pages_by_its_own_length():
    r = RangeState(); r.mode = "custom"
    r.custom_start, r.custom_end = dt.date(2026, 8, 1), dt.date(2026, 8, 10)
    assert r.bounds() == ("2026-08-01", "2026-08-10")
    assert len(r.days()) == 10
    r.shift(-1)
    assert r.bounds() == ("2026-07-22", "2026-07-31")   # ten days earlier
    r.shift(1)
    assert r.bounds() == ("2026-08-01", "2026-08-10")


def test_single_day_custom_range_is_not_multiday():
    r = RangeState(); r.mode = "custom"
    r.custom_start = r.custom_end = dt.date(2026, 8, 5)
    assert r.is_multiday is False


# --- rendering -------------------------------------------------------------

@pytest.fixture
def dash(tk_root, store, cfg):
    tracker = types.SimpleNamespace(cfg=cfg, paused=False, is_active=False,
                                    current_app_name="", current_file="")
    return Dashboard(tk_root, store, tracker=tracker)


def _pin_canvas(canvas, w, h):
    """The canvas is geometry-managed, so configure(width=…) doesn't stick;
    _draw_chart lays out from winfo_width/height."""
    canvas.winfo_width = lambda: w
    canvas.winfo_height = lambda: h


def test_builds_and_renders_every_range(dash, tk_root, store, today):
    store.add_seconds(today, "code.exe", "VS Code", "main.py", 3600)
    for mode in ("day", "week", "month", "year"):
        dash.range.set_mode(mode)
        dash.refresh()
        tk_root.update_idletasks()
    assert dash.total_label.cget("text")


def test_year_trend_uses_twelve_monthly_buckets(dash, tk_root, store):
    year = dt.date.today().year
    store.add_seconds(f"{year}-01-15", "code.exe", "VS Code", "a.py", 3600)
    store.add_seconds(f"{year}-03-02", "code.exe", "VS Code", "b.py", 1800)
    dash.range.set_mode("year")
    dash.refresh(); tk_root.update_idletasks()

    bars = dash._trend_bars()
    assert [b[0] for b in bars][:3] == ["Jan", "Feb", "Mar"]
    assert len(bars) == 12
    assert dict((l, v) for l, v, _ in bars)["Jan"] == 3600
    assert dash.trend_title.cget("text") == "MONTHLY TREND"


def test_long_custom_range_switches_to_monthly_buckets(dash, store):
    dash.range.mode = "custom"
    dash.range.custom_start = dt.date(2026, 1, 1)
    dash.range.custom_end = dt.date(2026, 12, 31)
    assert dash._trend_is_monthly() is True
    dash.range.custom_end = dt.date(2026, 1, 20)
    assert dash._trend_is_monthly() is False


def test_clicking_the_selected_app_deselects_it(dash, tk_root, store, today):
    store.add_seconds(today, "code.exe", "VS Code", "main.py", 120)
    dash.refresh(); tk_root.update_idletasks()

    dash.app_tree.selection_set("code.exe")
    dash._on_app_select()
    assert dash.chart_title.cget("text").startswith("TIME BY FILE")

    dash.app_tree.identify_row = lambda y: "code.exe"     # force the hit test
    assert dash._on_app_left_click(types.SimpleNamespace(y=10)) == "break"
    assert dash.selected_app is None
    assert dash.chart_title.cget("text") == "TOP APPLICATIONS"


def test_chart_shows_full_names_wrapped_not_elided(dash, tk_root, store, today):
    long_name = "SomeVeryLongProjectFolder/an_extremely_long_file_name_here.py"
    store.add_seconds(today, "code.exe", "VS Code", long_name, 3600)
    dash.refresh(); tk_root.update_idletasks()
    dash.app_tree.selection_set("code.exe"); dash._on_app_select()

    c = dash.chart
    _pin_canvas(c, 520, 300)
    dash._draw_chart(); tk_root.update_idletasks()

    texts = [c.itemcget(i, "text") for i in c.find_all() if c.type(i) == "text"]
    assert long_name in texts, "the full name should be drawn verbatim"
    assert not any("…" in t for t in texts if t != long_name)

    item = next(i for i in c.find_all()
                if c.type(i) == "text" and c.itemcget(i, "text") == long_name)
    x0, y0, x1, y1 = c.bbox(item)
    assert (y1 - y0) > 20, "a long name should wrap onto more than one line"
    label_w = max(120, (520 - 24) * 0.5)
    assert x1 < 12 + label_w + 12, "the label must not reach the bar column"


def test_chart_bars_leave_room_for_names_and_values(dash, tk_root, store, today):
    for i in range(3):
        store.add_seconds(today, "code.exe", "VS Code", f"f{i}.py", 100 * (i + 1))
    dash.refresh(); tk_root.update_idletasks()
    dash.app_tree.selection_set("code.exe"); dash._on_app_select()

    c = dash.chart
    W = 520
    _pin_canvas(c, W, 300)
    dash._draw_chart(); tk_root.update_idletasks()

    bars = [c.coords(i) for i in c.find_all() if c.type(i) == "rectangle"]
    assert bars
    label_w = max(120, (W - 24) * 0.5)
    assert all(b[0] >= label_w for b in bars), "bars must clear the name column"
    assert all(b[2] <= W - 12 - 68 + 1 for b in bars), "bars must clear the values"


def test_overflowing_rows_are_summarised(dash, tk_root, store, today):
    for i in range(12):
        store.add_seconds(today, "code.exe", "VS Code",
                          f"file_number_{i}_with_a_longish_name.py", 100 + i)
    dash.refresh(); tk_root.update_idletasks()
    dash.app_tree.selection_set("code.exe"); dash._on_app_select()

    c = dash.chart
    _pin_canvas(c, 420, 120)
    dash._draw_chart(); tk_root.update_idletasks()

    texts = [c.itemcget(i, "text") for i in c.find_all() if c.type(i) == "text"]
    assert any(t.startswith("+") and "more" in t for t in texts)
    assert max(c.bbox(i)[3] for i in c.find_all()) <= 125


def test_note_explains_files_or_sites_and_hides_on_the_app_view(
        dash, tk_root, store, today):
    store.add_seconds(today, "code.exe", "VS Code", "main.py", 60)
    store.add_seconds(today, "chrome.exe", "Chrome", "GitHub", 60)
    dash.refresh(); tk_root.update_idletasks()

    gridded = lambda w: bool(w.grid_info())   # withdrawn root -> ismapped is 0
    assert not gridded(dash.chart_note), "no note on the top-apps view"

    dash.app_tree.selection_set("code.exe"); dash._on_app_select()
    assert gridded(dash.chart_note)
    assert "Files" in dash.chart_note.cget("text")

    dash.app_tree.selection_set("chrome.exe"); dash._on_app_select()
    assert "Sites" in dash.chart_note.cget("text")


def test_merged_group_appears_as_one_row(tk_root, store, cfg, today):
    store.add_seconds(today, "godot.exe", "Godot", "main.tscn", 100)
    store.add_seconds(today, "godot_console.exe", "Godot", "", 50)
    cfg.merges = [{"name": "Godot",
                   "members": ["godot.exe", "godot_console.exe"]}]
    tracker = types.SimpleNamespace(cfg=cfg, paused=False, is_active=False,
                                    current_app_name="", current_file="")
    dash = Dashboard(tk_root, store, tracker=tracker)
    dash.refresh(); tk_root.update_idletasks()

    rows = dash.app_tree.get_children()
    assert "merge::Godot" in rows
    assert "godot.exe" not in rows


def test_right_click_actions_update_config(dash, tk_root, store, cfg, today):
    import tkinter as tk
    store.add_seconds(today, "code.exe", "VS Code", "main.py", 60)
    store.add_seconds(today, "game.exe", "Game", "", 60)
    dash.refresh(); tk_root.update_idletasks()

    dash.selected_app = "code.exe"
    dash._ctx_track_var = tk.BooleanVar(value=False)
    dash._ctx_toggle_track(["code.exe"])
    assert cfg.file_rules["code.exe"] == ["app"]

    dash._ctx_ignore(["game.exe"])
    tk_root.update_idletasks()
    assert "game.exe" in cfg.ignore_apps
    assert "game.exe" not in dash.app_tree.get_children()
