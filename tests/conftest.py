"""Shared test setup.

`config` resolves (and creates) the real per-user data directory at import time,
so the sandbox below must be installed *before* any project module is imported.
conftest is imported ahead of the test modules, which makes this the right place
for it — tests must never touch or migrate a developer's real data.
"""

from __future__ import annotations

import os
import pathlib
import sys
import tempfile

_SANDBOX = pathlib.Path(tempfile.mkdtemp(prefix="att-tests-"))
# Cover every platform's data-dir lookup: APPDATA (Windows), XDG_CONFIG_HOME
# (Linux), and HOME/USERPROFILE (macOS's ~/Library/Application Support).
for _var in ("APPDATA", "XDG_CONFIG_HOME", "HOME", "USERPROFILE"):
    os.environ[_var] = str(_SANDBOX)

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import pytest  # noqa: E402

import config  # noqa: E402
from storage import Storage  # noqa: E402


def pytest_configure() -> None:
    assert str(_SANDBOX) in config.APP_DIR, (
        f"tests must run against a sandbox, got {config.APP_DIR}")


@pytest.fixture
def cfg() -> config.Config:
    """A default config whose save() is a no-op (never writes to disk)."""
    c = config.Config()
    c.save = lambda: None  # type: ignore[method-assign]
    return c


@pytest.fixture
def store(tmp_path):
    """An empty Storage backed by a throwaway database."""
    s = Storage(str(tmp_path / "data.db"))
    yield s
    s.close()


@pytest.fixture(scope="session")
def _tk_session():
    """One Tk root for the whole run.

    Creating and destroying a root per test made Tk fail intermittently
    ("Can't find a usable init.tcl") on roughly half the runs, on a different
    test each time. One long-lived root avoids that churn entirely.
    """
    tk = pytest.importorskip("tkinter")
    try:
        root = tk.Tk()
    except tk.TclError as exc:  # headless CI without X/Wayland
        pytest.skip(f"no display available: {exc}")
    root.withdraw()
    yield root
    try:
        root.destroy()
    except Exception:
        pass


@pytest.fixture
def tk_root(_tk_session):
    """The shared root, emptied of the previous test's widgets."""
    def clear():
        for child in list(_tk_session.winfo_children()):
            try:
                child.destroy()
            except Exception:
                pass

    clear()
    yield _tk_session
    clear()


@pytest.fixture
def today() -> str:
    """Today's date — tests must never hard-code one (dates roll over)."""
    import datetime as dt
    return dt.date.today().isoformat()
