"""The "Edit record" window's parsing helpers."""

import pytest

from recordedit import NO_FILE, file_from_label, fmt_exact, parse_duration


@pytest.mark.parametrize("text,seconds", [
    ("1:20:00", 4800), ("20:00", 1200), ("0:00:45", 45),
    ("1h 20m", 4800), ("1h20m", 4800), ("45m", 2700), ("90s", 90),
    ("1.5h", 5400), ("20", 1200), (" 2m 5s ", 125),
])
def test_parse_duration(text, seconds):
    assert parse_duration(text) == seconds


@pytest.mark.parametrize("text", ["", "abc", "1:x", "1:2:3:4", "5 minutes",
                                  "1h and 2m"])
def test_parse_duration_rejects_nonsense(text):
    assert parse_duration(text) is None


@pytest.mark.parametrize("seconds", [0, 59, 3600, 4805.4, 90061])
def test_exact_format_reads_back(seconds):
    assert parse_duration(fmt_exact(seconds)) == round(seconds)


def test_no_file_label_means_the_untitled_record():
    assert file_from_label(f"  {NO_FILE} ") == ""
    assert file_from_label(" logo.psd ") == "logo.psd"
