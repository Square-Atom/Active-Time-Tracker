"""File Explorer's folder lookup over COM (Windows only).

The Shell is faked: CI must never depend on what Explorer windows happen to be
open, so these check how the answer is picked, not Explorer itself.
"""

import sys

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "win32",
                                reason="File Explorer is Windows-only")

HWND = 0x1234


class _Folder:
    def __init__(self, path):
        self.Self = type("Item", (), {"Path": path})()


class _Tab:
    """One entry of Shell.Application.Windows(): a window, or a tab of one."""

    def __init__(self, name, path, hwnd=HWND):
        self.HWND = hwnd
        self.LocationName = name
        self.Document = type("Doc", (), {"Folder": _Folder(path)})()


class _Windows:
    def __init__(self, *tabs):
        self._tabs = list(tabs)
        self.Count = len(self._tabs)

    def Item(self, i):
        return self._tabs[i]


@pytest.fixture
def explorer(monkeypatch):
    import winapi
    monkeypatch.setattr(winapi, "window_class", lambda hwnd: "CabinetWClass")

    def show(*tabs):
        monkeypatch.setattr(winapi, "_shell_windows", lambda: _Windows(*tabs))
    return winapi, show


def test_the_window_s_own_folder_is_returned_as_a_full_path(explorer):
    winapi, show = explorer
    show(_Tab("Music", r"C:\Users\hau\Music", hwnd=999),
         _Tab("Art", r"D:\Projects\Art"))
    assert winapi.explorer_folder(HWND, "Art - File Explorer") == r"D:\Projects\Art"


def test_the_tab_in_front_is_the_one_the_title_names(explorer):
    winapi, show = explorer
    show(_Tab("Doc", r"C:\Doc"), _Tab("Documents", r"C:\Users\hau\Documents"),
         _Tab("Downloads", r"C:\Users\hau\Downloads"))
    assert winapi.explorer_folder(
        HWND, "Documents and 2 more tabs - File Explorer") == r"C:\Users\hau\Documents"


def test_virtual_folders_use_their_name(explorer):
    winapi, show = explorer
    show(_Tab("This PC", "::{20D04FE0-3AEA-1069-A2D8-08002B30309D}"))
    assert winapi.explorer_folder(HWND, "This PC - File Explorer") == "This PC"


def test_the_desktop_is_not_a_folder(explorer, monkeypatch):
    winapi, _ = explorer
    monkeypatch.setattr(winapi, "window_class", lambda hwnd: "Progman")
    assert winapi.explorer_folder(HWND, "Program Manager") == ""


def test_without_pywin32_the_title_decides(explorer, monkeypatch):
    winapi, _ = explorer

    def missing():
        raise ImportError("no pywin32")
    monkeypatch.setattr(winapi, "_shell_windows", missing)
    assert winapi.explorer_folder(HWND, "Art - File Explorer") is None
