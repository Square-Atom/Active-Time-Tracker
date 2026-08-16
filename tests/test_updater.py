"""Update checking — version comparison and GitHub responses.

All network access is mocked: CI must not depend on GitHub being reachable, and
a rate-limited runner shouldn't turn into a red build.
"""

import json
import urllib.error
import urllib.request

import config
import pytest
import updater


@pytest.mark.parametrize("text,expected", [
    ("v1.2.3", (1, 2, 3)),
    ("1.0", (1, 0)),
    ("v2.0.0-beta", (2, 0, 0)),
    ("nonsense", (0,)),
])
def test_parse_version(text, expected):
    assert updater.parse_version(text) == expected


@pytest.mark.parametrize("latest,current,newer", [
    ("1.1.0", "1.0.0", True),
    ("1.0.1", "1.0.0", True),
    ("2.0", "1.9.9", True),
    ("v1.2.0", "1.1.0", True),
    ("1.0.0", "1.0.0", False),
    ("1.0", "1.0.0", False),      # differing precision, same version
    ("0.9", "1.0.0", False),
])
def test_is_newer(latest, current, newer):
    assert updater.is_newer(latest, current) is newer


@pytest.fixture
def github(monkeypatch):
    """Fake the GitHub API: yields a setter for the payload or exception."""
    state = {}

    class Resp:
        def read(self):
            return json.dumps(state["payload"]).encode()

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_urlopen(req, timeout=None):
        if state.get("exc"):
            raise state["exc"]
        return Resp()

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    def configure(payload=None, exc=None):
        state["payload"], state["exc"] = payload, exc

    return configure


def test_newer_release_is_reported(github):
    github({"tag_name": "v2.5.0", "html_url": "https://example/releases/v2.5.0"})
    result = updater.check("1.0.0")
    assert result.status == "update"
    assert result.latest == "2.5.0"
    assert result.has_update is True


def test_same_version_is_current(github):
    github({"tag_name": "v1.0.0", "html_url": "u"})
    assert updater.check("1.0.0").status == "current"


def test_missing_tag_means_no_releases(github):
    github({"tag_name": "", "html_url": "u"})
    assert updater.check("1.0.0").status == "none"


@pytest.mark.parametrize("code,status", [(404, "none"), (403, "error"),
                                         (429, "error"), (500, "error")])
def test_http_errors(github, code, status):
    github(exc=urllib.error.HTTPError("u", code, "err", {}, None))
    result = updater.check("1.0.0")
    assert result.status == status
    assert result.message           # always explains itself to the user


def test_offline_is_an_error_not_a_crash(github):
    github(exc=urllib.error.URLError("offline"))
    result = updater.check("1.0.0")
    assert result.status == "error" and not result.has_update


def test_garbled_response_is_handled(github, monkeypatch):
    class Bad:
        def read(self):
            return b"not json"

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: Bad())
    assert updater.check("1.0.0").status == "error"


# --- the message a release can carry -------------------------------------

def test_no_body_means_no_custom_message():
    assert updater.announcement(None) == ""
    assert updater.announcement("   \n  ") == ""


def test_the_release_body_becomes_the_message():
    assert updater.announcement("Please update — this fixes data loss.") == \
        "Please update — this fixes data loss."


def test_markers_pick_out_just_the_announcement():
    """So a long changelog can live in the release without filling the dialog."""
    body = ("## Changelog\n- lots\n- of\n- detail\n\n"
            f"{updater.ANNOUNCE_START}\n"
            "Important: back up before installing.\n"
            f"{updater.ANNOUNCE_END}\n\n## More detail\n- ignored")
    assert updater.announcement(body) == "Important: back up before installing."


def test_a_long_body_is_trimmed_to_fit_a_dialog():
    note = updater.announcement("\n".join(f"line {i}" for i in range(50)))
    assert note.count("\n") <= 10
    assert note.endswith("…")


def test_a_very_wide_body_is_capped_by_characters():
    note = updater.announcement("x" * 5000)
    assert len(note) < 800 and note.endswith("…")


def test_markdown_rules_are_dropped():
    assert updater.announcement("Heads up\n=====\n\nDetails here") == \
        "Heads up\nDetails here"


def test_the_message_reaches_the_result(github):
    github({"tag_name": "v9.0.0", "html_url": "u",
            "body": "Critical: update as soon as you can."})
    result = updater.check("1.0.0")
    assert result.has_update
    assert result.notes == "Critical: update as soon as you can."


def test_a_release_without_a_body_leaves_notes_empty(github):
    github({"tag_name": "v9.0.0", "html_url": "u"})
    assert updater.check("1.0.0").notes == ""


def test_app_version_matches_release_tag_format():
    """APP_VERSION must be a bare version — the update check compares it to the
    GitHub tag, so a stale or v-prefixed value misreports updates."""
    assert not config.APP_VERSION.lower().startswith("v")
    assert updater.parse_version(config.APP_VERSION) >= (1, 0)


# --- the popup itself ------------------------------------------------------

def _all_text(widget):
    found = []
    for child in widget.winfo_children():
        try:
            found.append(str(child.cget("text")))
        except Exception:
            pass
        found.extend(_all_text(child))
    return found


def test_the_popup_shows_a_custom_message_when_there_is_one(tk_root):
    import updatedialog
    result = updater.UpdateResult("update", latest="9.9.9",
                                  notes="Please update: this fixes data loss.")
    updatedialog.show_update(tk_root, result)
    tk_root.update_idletasks()

    win = tk_root.winfo_children()[-1]
    blob = " ".join(_all_text(win))
    assert "Please update: this fixes data loss." in blob
    assert "9.9.9" in blob, "the version must still be shown"
    win.destroy()


def test_the_popup_falls_back_to_its_own_wording(tk_root):
    import updatedialog
    updatedialog.show_update(tk_root, updater.UpdateResult("update", latest="9.9.9"))
    tk_root.update_idletasks()

    win = tk_root.winfo_children()[-1]
    blob = " ".join(_all_text(win))
    assert "9.9.9" in blob and "available on GitHub" in blob
    win.destroy()


def test_check_async_delivers_a_result(github):
    github({"tag_name": "v9.9.9", "html_url": "u"})
    seen = []
    done = __import__("threading").Event()

    def cb(result):
        seen.append(result)
        done.set()

    updater.check_async(cb, "1.0.0")
    assert done.wait(10), "callback never fired"
    assert seen[0].has_update is True
