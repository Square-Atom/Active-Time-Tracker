"""The app's clock icon, shared by the tray, the window, and the .exe build."""

from __future__ import annotations

from PIL import Image, ImageDraw


def make_clock_image(size: int = 64) -> Image.Image:
    s = size
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    f = s / 64.0
    d.ellipse((4 * f, 4 * f, 60 * f, 60 * f), fill=(124, 156, 255, 255))
    d.ellipse((10 * f, 10 * f, 54 * f, 54 * f), fill=(30, 31, 43, 255))
    # clock hands
    d.line((32 * f, 32 * f, 32 * f, 16 * f), fill=(232, 232, 240, 255),
           width=max(2, round(4 * f)))
    d.line((32 * f, 32 * f, 45 * f, 38 * f), fill=(232, 232, 240, 255),
           width=max(2, round(4 * f)))
    d.ellipse((29 * f, 29 * f, 35 * f, 35 * f), fill=(124, 156, 255, 255))
    return img


def save_ico(path: str) -> None:
    """Write a multi-resolution .ico for the packaged executable."""
    base = make_clock_image(256)
    sizes = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
    base.save(path, format="ICO", sizes=sizes)


def ensure_ico() -> str | None:
    """Path to an .ico on disk, generating one in the data dir if needed.

    Windows needs a real .ico file (not a Tk photo image) before it will show
    our icon in the title bar and taskbar. Returns None if it can't be written —
    the icon is cosmetic, so callers should carry on.
    """
    import os
    import sys

    # A packaged build ships one next to the executable; prefer that.
    if getattr(sys, "frozen", False):
        bundled = os.path.join(getattr(sys, "_MEIPASS", ""), "app.ico")
        if os.path.exists(bundled):
            return bundled
    here = os.path.join(os.path.dirname(os.path.abspath(__file__)), "app.ico")
    if os.path.exists(here):
        return here
    try:
        import config
        path = os.path.join(config.APP_DIR, "app.ico")
        if not os.path.exists(path):
            save_ico(path)
        return path
    except Exception:
        return None


if __name__ == "__main__":
    import os
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "app.ico")
    save_ico(out)
    print("wrote", out)
