"""Draws the app icon (a translation bubble pair: A -> 文) for Windows (.ico) and Android (adaptive icon layers)."""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
FONT = r"C:\Windows\Fonts\msjhbd.ttc"
FONT_LATIN = r"C:\Windows\Fonts\segoeuib.ttf"


def bubble(d, box, fill, tail_left, scale):
    x0, y0, x1, y1 = box
    d.rounded_rectangle(box, radius=int(70 * scale), fill=fill)
    tx = x0 + int(60 * scale) if tail_left else x1 - int(60 * scale)
    d.polygon([(tx, y1 - 4), (tx + int(70 * scale) * (1 if tail_left else -1), y1 - 4), (tx, y1 + int(80 * scale))], fill=fill)


def glyphs(size, with_background):
    """The two bubbles on a [size] square. With a background it is the full icon; without, only the artwork."""
    s = size / 1024
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    if with_background:
        grad = Image.new("RGBA", (size, size))
        gd = ImageDraw.Draw(grad)
        for y in range(size):
            t = y / size
            gd.line([(0, y), (size, y)], fill=(int(40 + 40 * t), int(44 + 20 * t), int(120 + 100 * t), 255))
        mask = Image.new("L", (size, size), 0)
        ImageDraw.Draw(mask).rounded_rectangle((0, 0, size - 1, size - 1), radius=int(230 * s), fill=255)
        img.paste(grad, (0, 0), mask)
        d = ImageDraw.Draw(img)
    # the artwork sits inside the middle 66% so an adaptive icon's mask never cuts it
    a, b = 0.2 * size, 0.8 * size
    w = b - a
    bubble(d, (a, a + 0.04 * size, a + 0.62 * w, a + 0.04 * size + 0.5 * w), (255, 255, 255, 255), True, s)
    bubble(d, (a + 0.38 * w, a + 0.38 * w, b, a + 0.38 * w + 0.5 * w), (255, 214, 64, 255), False, s)
    big = ImageFont.truetype(FONT_LATIN, int(0.36 * w))
    cjk = ImageFont.truetype(FONT, int(0.34 * w))
    d.text((a + 0.31 * w, a + 0.04 * size + 0.25 * w), "A", font=big, fill=(30, 33, 90, 255), anchor="mm")
    d.text((a + 0.69 * w, a + 0.38 * w + 0.25 * w), "文", font=cjk, fill=(30, 33, 90, 255), anchor="mm")
    return img


def main():
    full = glyphs(1024, True)
    (ROOT / "assets").mkdir(exist_ok=True)
    full.resize((512, 512), Image.LANCZOS).save(ROOT / "assets" / "icon.png")
    full.save(ROOT / "assets" / "icon.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    res = ROOT / "android" / "app" / "src" / "main" / "res"
    (res / "drawable-nodpi").mkdir(parents=True, exist_ok=True)
    glyphs(432, False).save(res / "drawable-nodpi" / "ic_launcher_foreground.png")
    (res / "mipmap-anydpi-v26").mkdir(parents=True, exist_ok=True)


if __name__ == "__main__":
    main()
