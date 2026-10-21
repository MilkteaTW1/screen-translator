"""Transparent, click-through overlay that draws each translation directly above its text block."""
import ctypes

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QPainter
from PySide6.QtWidgets import QWidget

WDA_EXCLUDEFROMCAPTURE = 0x11


class Overlay(QWidget):
    def __init__(self, screen):
        super().__init__()
        self.setWindowFlags(
            Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool | Qt.WindowTransparentForInput
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setGeometry(screen.geometry())
        self.scale = screen.devicePixelRatio()
        self.items = []  # (x, y, w, h, text-or-None, line_height) in physical pixels
        self.drawn = {}  # text -> box it was drawn in (for tests)

    def set_capture_hidden(self, hidden):
        """Hidden: screenshots (and our own OCR) never see the translations. Shown: users can
        screenshot them, and the worker skips text that matches its own output."""
        ctypes.windll.user32.SetWindowDisplayAffinity(
            int(self.winId()), WDA_EXCLUDEFROMCAPTURE if hidden else 0)

    def set_items(self, items):
        # OCR boxes wobble by a few pixels between scans. Keep the previous box when the same text
        # is still roughly where it was, so translations don't shiver.
        steady = []
        for x, y, w, h, text, lh in items:
            for ox, oy, ow, oh, otext, olh in self.items:
                if otext == text and abs(ox - x) <= 8 and abs(oy - y) <= 8 and abs(ow - w) <= 12:
                    x, y, w, h, lh = ox, oy, ow, oh, olh
                    break
            steady.append((x, y, w, h, text, lh))
        if steady != self.items:
            self.items = steady
            self.update()

    def paintEvent(self, _):
        self.draw(QPainter(self))

    def draw(self, p):
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)
        self.drawn = {}
        for x, y, w, h, text, lh in self.items:
            if not text:  # untranslated line: nothing to draw
                continue
            rect, font = self._box(text, QRectF(x, y, w, h) if self.scale == 1 else
                                   QRectF(x / self.scale, y / self.scale, w / self.scale, h / self.scale),
                                   lh / self.scale)
            self.drawn[text] = rect
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(20, 20, 20, 225))
            p.drawRoundedRect(rect, 4, 4)
            p.setFont(font)
            p.setPen(QColor(255, 235, 140))
            p.drawText(rect.adjusted(6, 0, -6, 0), Qt.AlignVCenter | Qt.AlignLeft | Qt.TextWordWrap, text)

    def _box(self, text, src, line_height):
        """The translation box: directly above the text block, centred on it.

        Where it goes depends only on the block itself, never on what happens to be around it, so
        it cannot hop between above, below and beside when something nearby appears or vanishes."""
        size = max(14, min(28, int(line_height * 0.85)))
        font = QFont("Microsoft JhengHei UI")
        font.setPixelSize(size)
        maxw = min(max(src.width(), 260), self.width() - 8)
        r = QFontMetricsF(font).boundingRect(QRectF(0, 0, maxw - 12, 10000), int(Qt.TextWordWrap), text)
        tw, th = r.width() + 12, r.height() + 4
        x = min(max(src.center().x() - tw / 2, 0), self.width() - tw)
        y = max(src.y() - th - 2, 0)
        return QRectF(x, y, tw, th), font
