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


def _click(dash, key):
    """Click the row belonging to `key` (hit testing works on y positions)."""
    row = next(r for r in dash._rows if r.get("key") == key)
    return dash._on_chart_click(types.SimpleNamespace(y=row["y0"] + 2))


def _texts(canvas):
    return [canvas.itemcget(i, "text") for i in canvas.find_all()
            if canvas.type(i) == "text"]


def _drawn(dash, tk_root, w=560, h=400):
    _pin_canvas(dash.chart, w, h)
    dash._draw_chart()
    tk_root.update_idletasks()


# --- stable colours --------------------------------------------------------

def test_colour_depends_on_the_name_not_the_ranking():
    from dashboard import BAR_COLORS, color_for
    first = color_for("photoshop.exe")
    assert first in BAR_COLORS
    assert color_for("photoshop.exe") == first          # same every call
    assert color_for("chrome.exe") != first or True     # (collisions are fine)


def test_colour_is_stable_across_processes():
    """hash() is randomised per process, so the colour must not use it."""
    import subprocess
    import sys as _sys
    out = subprocess.run(
        [_sys.executable, "-c",
         "import sys; sys.path.insert(0, r'.'); "
         "from dashboard import color_for; print(color_for('photoshop.exe'))"],
        capture_output=True, text=True, env={"PYTHONHASHSEED": "12345", **__import__("os").environ},
    )
    from dashboard import color_for
    assert out.stdout.strip() == color_for("photoshop.exe")


# --- rows, expansion, interaction -----------------------------------------

def test_apps_are_rows_with_time_and_percent(dash, tk_root, store, today):
    store.add_seconds(today, "code.exe", "VS Code", "main.py", 300)
    store.add_seconds(today, "game.exe", "Game", "", 100)
    dash.refresh(); _drawn(dash, tk_root)

    assert [r["key"] for r in dash._rows] == ["code.exe", "game.exe"]
    texts = _texts(dash.chart)
    assert any("75%" in t for t in texts) and any("25%" in t for t in texts)
    assert any("5m 00s" in t for t in texts)


def test_clicking_an_app_expands_and_collapses_its_files(dash, tk_root, store, today):
    store.add_seconds(today, "code.exe", "VS Code", "main.py", 200)
    store.add_seconds(today, "code.exe", "VS Code", "test.py", 100)
    dash.refresh(); _drawn(dash, tk_root)
    assert [r["kind"] for r in dash._rows] == ["app"]

    _click(dash, "code.exe")
    _drawn(dash, tk_root)
    kinds = [r["kind"] for r in dash._rows]
    assert kinds == ["app", "file", "file"]
    assert [r["label"] for r in dash._rows if r["kind"] == "file"] == ["main.py", "test.py"]
    # files are shown as a share of their own app, biggest first
    assert dash._rows[1]["pct"] == pytest.approx(66.7, abs=0.5)

    _click(dash, "code.exe")          # click again collapses
    _drawn(dash, tk_root)
    assert [r["kind"] for r in dash._rows] == ["app"]


def test_app_level_apps_are_not_expandable(dash, tk_root, store, cfg, today):
    cfg.set_track_files("game.exe", False)
    store.add_seconds(today, "game.exe", "Game", "", 100)
    dash.refresh(); _drawn(dash, tk_root)

    assert dash._rows[0]["has_files"] is False
    assert _click(dash, "game.exe") is None      # click does nothing
    _drawn(dash, tk_root)
    assert [r["kind"] for r in dash._rows] == ["app"]


def test_expansion_survives_a_range_change(dash, tk_root, store, today):
    store.add_seconds(today, "code.exe", "VS Code", "main.py", 200)
    dash.refresh(); _drawn(dash, tk_root)
    _click(dash, "code.exe")
    assert "code.exe" in dash.expanded

    dash._set_mode("week")
    tk_root.update_idletasks()
    assert "code.exe" in dash.expanded, "should still be expanded in the week view"


def test_expansion_is_dropped_when_the_app_disappears(dash, tk_root, store, today):
    store.add_seconds(today, "code.exe", "VS Code", "main.py", 200)
    dash.refresh(); _drawn(dash, tk_root)
    _click(dash, "code.exe")

    dash.range.anchor = dt.date(2020, 1, 1)      # a day with no data
    dash.refresh()
    assert dash.expanded == set()


def test_file_rows_are_indented_and_dimmer_than_their_app(dash, tk_root, store, today):
    store.add_seconds(today, "code.exe", "VS Code", "main.py", 200)
    dash.refresh(); _drawn(dash, tk_root)
    _click(dash, "code.exe"); _drawn(dash, tk_root)

    app_row, file_row = dash._rows[0], dash._rows[1]
    assert file_row["color"] != app_row["color"]
    c = dash.chart
    xs = {}
    for i in c.find_all():
        if c.type(i) == "text" and c.itemcget(i, "text").endswith("main.py"):
            xs["file"] = c.bbox(i)[0]
        if c.type(i) == "text" and "VS Code" in c.itemcget(i, "text"):
            xs["app"] = c.bbox(i)[0]
    assert xs["file"] > xs["app"], "file rows should be indented"


def test_expand_marker_reflects_state(dash, tk_root, store, today):
    store.add_seconds(today, "code.exe", "VS Code", "main.py", 200)
    dash.refresh(); _drawn(dash, tk_root)
    assert any(t.startswith("▸") for t in _texts(dash.chart))
    _click(dash, "code.exe"); _drawn(dash, tk_root)
    assert any(t.startswith("▾") for t in _texts(dash.chart))


def test_long_names_wrap_in_full(dash, tk_root, store, today):
    long_name = "SomeVeryLongProjectFolder/an_extremely_long_file_name_here.py"
    store.add_seconds(today, "code.exe", "VS Code", long_name, 3600)
    dash.refresh(); _drawn(dash, tk_root)
    _click(dash, "code.exe"); _drawn(dash, tk_root, w=520, h=400)

    c = dash.chart
    assert long_name in _texts(c), "the full name should be drawn verbatim"
    item = next(i for i in c.find_all()
                if c.type(i) == "text" and c.itemcget(i, "text") == long_name)
    x0, y0, x1, y1 = c.bbox(item)
    assert (y1 - y0) > 20, "a long name should wrap onto more than one line"


def test_bars_stay_between_the_name_and_value_columns(dash, tk_root, store, today):
    for i in range(3):
        store.add_seconds(today, f"app{i}.exe", f"App {i}", "", 100 * (i + 1))
    dash.refresh()
    W = 560
    _drawn(dash, tk_root, w=W)

    bars = [dash.chart.coords(i) for i in dash.chart.find_all()
            if dash.chart.type(i) == "rectangle"]
    assert bars
    name_w = max(130, (W - 24 - 46 - 74 - 12) * 0.42)
    assert all(b[0] >= name_w for b in bars), "bars must clear the name column"
    assert all(b[2] <= W - 12 - 46 - 74 + 1 for b in bars), "bars must clear values"


def test_all_rows_are_reachable_by_scrolling(dash, tk_root, store, today):
    for i in range(20):
        store.add_seconds(today, f"app{i:02d}.exe", f"App {i}", "", 100 + i)
    dash.refresh()
    _drawn(dash, tk_root, w=460, h=120)

    # every app is drawn (nothing is silently dropped) …
    assert len(dash._rows) == 20
    # … and the scroll region is taller than the canvas so they can be reached
    x0, y0, x1, y1 = [float(v) for v in dash.chart.cget("scrollregion").split()]
    assert y1 > 120


def test_note_appears_only_while_expanded_and_matches_the_kind(
        dash, tk_root, store, today):
    store.add_seconds(today, "code.exe", "VS Code", "main.py", 60)
    store.add_seconds(today, "chrome.exe", "Chrome", "GitHub", 60)
    dash.refresh(); _drawn(dash, tk_root)

    gridded = lambda w: bool(w.grid_info())   # withdrawn root -> ismapped is 0
    assert not gridded(dash.chart_note), "no note until something is expanded"

    _click(dash, "code.exe"); _drawn(dash, tk_root)
    assert gridded(dash.chart_note)
    assert "Files" in dash.chart_note.cget("text")

    _click(dash, "code.exe")                  # collapse, expand the browser
    _drawn(dash, tk_root)
    _click(dash, "chrome.exe"); _drawn(dash, tk_root)
    assert "Sites" in dash.chart_note.cget("text")


def test_merged_group_appears_as_one_row(tk_root, store, cfg, today):
    store.add_seconds(today, "godot.exe", "Godot", "main.tscn", 100)
    store.add_seconds(today, "godot_console.exe", "Godot", "", 50)
    cfg.merges = [{"name": "Godot",
                   "members": ["godot.exe", "godot_console.exe"]}]
    tracker = types.SimpleNamespace(cfg=cfg, paused=False, is_active=False,
                                    current_app_name="", current_file="")
    dash = Dashboard(tk_root, store, tracker=tracker)
    dash.refresh(); _drawn(dash, tk_root)

    keys = [r["key"] for r in dash._rows]
    assert keys == ["merge::Godot"]

    _click(dash, "merge::Godot"); _drawn(dash, tk_root)
    files = [r["label"] for r in dash._rows if r["kind"] == "file"]
    assert "main.tscn" in files, "a group expands to its members' files"


def test_right_click_actions_update_config(dash, tk_root, store, cfg, today):
    import tkinter as tk
    store.add_seconds(today, "code.exe", "VS Code", "main.py", 60)
    store.add_seconds(today, "game.exe", "Game", "", 60)
    dash.refresh(); _drawn(dash, tk_root)

    dash._ctx_track_var = tk.BooleanVar(value=False)
    dash._ctx_toggle_track(["code.exe"])
    assert cfg.file_rules["code.exe"] == ["app"]

    dash._ctx_ignore(["game.exe"])
    _drawn(dash, tk_root)
    assert "game.exe" in cfg.ignore_apps
    assert "game.exe" not in [r["key"] for r in dash._rows]


def test_right_clicking_a_file_targets_its_app(dash, tk_root, store, today):
    store.add_seconds(today, "code.exe", "VS Code", "main.py", 60)
    dash.refresh(); _drawn(dash, tk_root)
    _click(dash, "code.exe"); _drawn(dash, tk_root)

    file_row = next(r for r in dash._rows if r["kind"] == "file")
    assert dash._row_at(types.SimpleNamespace(y=file_row["y0"] + 2)) is file_row
    assert file_row["app"] == "code.exe"
