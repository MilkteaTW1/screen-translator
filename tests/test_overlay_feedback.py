"""When screenshots are allowed to include translations, our own translation boxes end up in the picture we read.
That used to make the translations flicker: a box appears, the picture changes, the text under it is read differently,
the translation goes away, the picture changes again... Here the overlay is composited into the captured picture the
way the screen would show it."""
import time

import numpy as np
import pytest
from PIL import Image, ImageDraw, ImageFont
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication

from screen_translator import app as appmod
from screen_translator import ocr
from screen_translator.overlay import Overlay

PARAGRAPHS = [
    "If you are looking to improve your English conversational skills or just trying to refine what you already know.",
    "Professor Alex is a Certified English Teacher who can help you with your kids how to write in English.",
    "He finds new ways to help your kids understand sentence structure, grammar, and punctuation every day.",
    "Do not think he stops there, this teacher teaches all grades from elementary school through high school.",
]


def page(width=1200, height=1900):
    img = Image.new("RGB", (width, height), "white")
    d = ImageDraw.Draw(img)
    font = ImageFont.truetype("arial.ttf", 22)
    y = 40
    for text in PARAGRAPHS * 4:  # a full page: no room beside the text, so translations must cover it
        words, line = text.split(), ""
        for w in words:
            if d.textlength(line + " " + w, font=font) > 560:
                d.text((80, y), line.strip(), font=font, fill="black")
                y, line = y + 32, ""
            line += " " + w
        d.text((80, y), line.strip(), font=font, fill="black")
        y += 36
    return np.asarray(img.convert("RGBA"))[:, :, [2, 1, 0, 3]].copy()


class Shot:
    def __init__(self, a):
        self.bgra, self.width, self.height = a.tobytes(), a.shape[1], a.shape[0]


def composite(base, overlay):
    img = overlay.grab().toImage().convertToFormat(QImage.Format_ARGB32)
    top = np.frombuffer(img.constBits(), np.uint8).reshape(img.height(), img.width(), 4).astype(np.float32)
    alpha = top[:, :, 3:4] / 255.0
    out = base.astype(np.float32)
    out[:, :, :3] = top[:, :, :3] * alpha + out[:, :, :3] * (1 - alpha)
    return out.astype(np.uint8)


def run(monkeypatch, mask, steps=16):
    qapp = QApplication.instance() or QApplication([])
    try:
        recognizer = ocr.Recognizer("en-US")
    except RuntimeError:
        pytest.skip("no English OCR installed in Windows")
    base = page()
    overlay = Overlay(qapp.primaryScreen())
    overlay.scale = 1.0
    overlay.setGeometry(0, 0, base.shape[1], base.shape[0])
    worker = appmod.Worker(appmod.LANGUAGES)
    worker.settings = {**appmod.DEFAULTS, "hide_from_capture": False, "interval": 0.0}
    worker.mask_own_overlay = mask
    worker.overlay_rects = overlay.painted_rects
    worker._recognizer = recognizer
    worker.results.connect(overlay.set_items)
    monkeypatch.setattr(worker.translator, "translate_many",
                        lambda texts, *a: [("這是一段很長的翻譯內容" * 40)[:len(t) // 2] for t in texts])  # about as long as real ones
    scans, orig = [], worker._process
    worker._process = lambda *a: (scans.append(1), orig(*a))[1]
    shown, flips = [], 0
    for k in range(steps):
        worker._step(Shot(composite(base, overlay)), time.monotonic())
        overlay.grab()  # paint, so the next picture has the boxes in it
        now = set(overlay.drawn)
        if shown and k > 3:
            flips += len(shown[-1] ^ now)
        shown.append(now)
    return len(scans), flips, len(shown[-1])


def test_translations_stay_put_when_our_own_boxes_are_in_the_picture(monkeypatch):
    scans, flips, count = run(monkeypatch, mask=True)
    assert count >= 3
    assert flips == 0 and scans <= 3  # read once or twice, then left alone


def test_without_the_fix_the_same_screen_flickers(monkeypatch):
    scans, flips, _count = run(monkeypatch, mask=False)
    assert flips >= 3
