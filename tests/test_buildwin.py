"""The Windows build script (build-time, but it must track APP_VERSION)."""

import os

import buildwin
import config

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_version_is_read_from_config_source():
    # Read without importing config, so building never touches the data folder.
    assert buildwin.app_version(os.path.join(ROOT, "config.py")) == config.APP_VERSION


def test_file_version_pads_to_four_numbers():
    assert buildwin.file_version("1.5.1") == "1.5.1.0"
    assert buildwin.file_version("2.0") == "2.0.0.0"
    assert buildwin.file_version("1.2.3.4") == "1.2.3.4"


def test_nuitka_args_name_the_product_and_version():
    args = buildwin.nuitka_args("1.5.2", 2026, python="py")
    assert args[:3] == ["py", "-m", "nuitka"]
    assert args[-1] == "main.py"
    for expected in ("--standalone",
                     "--windows-console-mode=disable",
                     "--include-module=pystray._win32",
                     "--file-version=1.5.2.0",
                     "--product-name=Active Time Tracker",
                     "--company-name=Pixelmancer Studio",
                     "--output-filename=ActiveTimeTracker.exe"):
        assert expected in args
    # onefile unpacks-and-relaunches, which is exactly what scanners distrust
    assert "--onefile" not in args
