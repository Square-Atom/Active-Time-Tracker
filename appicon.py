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


if __name__ == "__main__":
    import os
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "app.ico")
    save_ico(out)
    print("wrote", out)
