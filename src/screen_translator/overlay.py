"""Transparent, click-through overlay. Each translation goes in empty space next to its text block
(above, centred, if there is room; else below) and is laid over the text when there is no room."""
import ctypes
import time

from PySide6.QtCore import QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QPainter
from PySide6.QtWidgets import QWidget

WDA_EXCLUDEFROMCAPTURE = 0x11


class Overlay(QWidget):
    covers_changed = Signal(bool)
    STEP = 4

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
        self.modes = {}  # text -> 'above' | 'below' | 'cover', decided once so a translation never hops around
        self.luma = None  # coarse brightness map of the screen (one cell per STEP pixels), to find empty space
        self.luma_origin = (0, 0)
        self.hide_covers = False  # translations laid over text can be switched off with the chip
        self.has_covers = False
        self.painted = []  # (x0, y0, x1, y1) in physical pixels of every translation box currently drawn

    def painted_rects(self):
        return self.painted

    def set_capture_hidden(self, hidden):
        """Hidden: screenshots (and our own OCR) never see the translations. Shown: users can
        screenshot them, and the worker skips text that matches its own output."""
        ctypes.windll.user32.SetWindowDisplayAffinity(
            int(self.winId()), WDA_EXCLUDEFROMCAPTURE if hidden else 0)

    def set_background(self, luma, origin=(0, 0)):
        """The latest screenshot as a coarse brightness map; lets us tell empty space (of any colour) from text."""
        self.luma, self.luma_origin = luma, origin

    def is_blank(self, r):
        """True if the logical-pixel rectangle [r] is one flat colour on the screen (nothing drawn there)."""
        if self.luma is None:
            return True
        k, st = self.scale, self.STEP
        ox, oy = self.luma_origin
        x0, x1 = int((r.left() * k - ox) // st), int((r.right() * k - ox) // st)
        y0, y1 = int((r.top() * k - oy) // st), int((r.bottom() * k - oy) // st)
        rows, cols = self.luma.shape
        if x0 < 0 or y0 < 0 or x1 >= cols or y1 >= rows or x1 - x0 < 1 or y1 - y0 < 1:
            return False
        cell = self.luma[y0:y1 + 1, x0:x1 + 1].astype(int)
        return (abs(cell - cell.mean()) > 14).mean() <= 0.03

    def set_items(self, items):
        # OCR boxes wobble by a few pixels between scans. Keep the previous box when the same text
        # is still roughly where it was, so translations don't shiver.
        steady = []
        old = {i[4]: i for i in self.items if i[4]}
        moves = [(x - old[t][0], y - old[t][1]) for x, y, _w, _h, t, _lh in items if t in old]
        if moves:  # everything moved together by more than a wobble: the page scrolled, follow it exactly
            mx = sorted(m[0] for m in moves)[len(moves) // 2]
            my = sorted(m[1] for m in moves)[len(moves) // 2]
            if max(abs(mx), abs(my)) >= 3 and sum(abs(a - mx) <= 2 and abs(b - my) <= 2 for a, b in moves) >= 0.7 * len(moves):
                if items != self.items:
                    self.items = list(items)
                    # where a translation could not go beside its text was decided on another part of the page
                    self.modes = {t: m for t, m in self.modes.items() if m != "cover"}
                    self.update()
                return
        for x, y, w, h, text, lh in items:
            for ox, oy, ow, oh, otext, olh in self.items:
                if otext == text and abs(ox - x) <= 8 and abs(oy - y) <= 8 and abs(ow - w) <= 12:
                    x, y, w, h, lh = ox, oy, ow, oh, olh
                    break
            steady.append((x, y, w, h, text, lh))
        if steady != self.items:
            self.items = steady
            texts = {i[4] for i in steady}
            self.modes = {t: m for t, m in self.modes.items() if t in texts}
            self.update()

    def paintEvent(self, _):
        self.draw(QPainter(self))

    def draw(self, p):
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)
        self.drawn = {}
        painted = []
        k = self.scale
        srcs = [(QRectF(x / k, y / k, w / k, h / k), text, lh / k) for x, y, w, h, text, lh in self.items]
        placed = []  # translation boxes already placed (logical pixels)
        for i, (src, text, lh) in enumerate(srcs):
            if not text:  # untranslated line: nothing to draw
                continue
            mode = self.modes.get(text)
            if mode is None:
                others = [r for j, (r, _t, _l) in enumerate(srcs) if j != i] + placed
                mode = self.modes[text] = self._decide(text, src, lh, others)
            rect, font = self._box(text, src, lh, mode)
            if mode != "cover":
                placed.append(rect)
            self.drawn[text] = rect
            if mode == "cover" and self.hide_covers:
                continue
            painted.append((rect.left() * k, rect.top() * k, rect.right() * k, rect.bottom() * k))
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(20, 20, 20, 255 if mode == "cover" else 225))  # a cover must hide the text under it
            p.drawRoundedRect(rect, 4, 4)
            p.setFont(font)
            p.setPen(QColor(255, 235, 140))
            align = Qt.AlignCenter if mode == "cover" else Qt.AlignVCenter | Qt.AlignLeft  # a cover reads as a label
            p.drawText(rect.adjusted(6, 0, -6, 0), align | Qt.TextWordWrap, text)
        self.painted = painted
        covers = any(m == "cover" for m in self.modes.values())
        if covers != self.has_covers:
            self.has_covers = covers
            self.covers_changed.emit(covers)

    def _decide(self, text, src, lh, others):
        """Empty space next to the block if there is some (above first, then below), else lay it over the text."""
        for mode in ("above", "below"):
            rect, _ = self._box(text, src, lh, mode)
            if self.is_blank(rect) and not any(rect.intersects(o) for o in others):
                return mode
        return "cover"

    def _box(self, text, src, line_height, mode="above"):
        """The translation box. Its place is decided once, when the text is first shown, and then kept."""
        size = max(14, min(28, int(line_height * 0.85)))
        font = QFont("Microsoft JhengHei UI")
        if mode == "cover":
            # Hide the whole source block, and keep the text readable: widen (then grow) the box rather than
            # shrinking the letters until nobody can read them.
            size = max(size, 15)
            font.setPixelSize(size)
            metrics = QFontMetricsF(font)
            natural = metrics.horizontalAdvance(text) + 14
            w = min(max(src.width(), 40, min(natural, src.width() * 1.6)), self.width() - src.x() - 4)
            th = metrics.boundingRect(QRectF(0, 0, w - 12, 10000), int(Qt.TextWordWrap), text).height() + 4
            return QRectF(src.x(), src.y(), w, max(src.height(), th)), font
        font.setPixelSize(size)
        maxw = min(max(src.width(), 260), self.width() - 8)
        r = QFontMetricsF(font).boundingRect(QRectF(0, 0, maxw - 12, 10000), int(Qt.TextWordWrap), text)
        tw, th = r.width() + 12, r.height() + 4
        x = min(max(src.center().x() - tw / 2, 0), self.width() - tw)
        y = src.bottom() + 2 if mode == "below" else max(src.y() - th - 2, 0)
        return QRectF(x, y, tw, th), font


class CoverChip(QWidget):
    """A small round button that appears while a translation covers text; one click hides or shows those covers."""

    def __init__(self, overlay):
        super().__init__()
        self.overlay = overlay
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setFixedSize(40, 40)
        geo = overlay.geometry()
        self.move(geo.right() - 56, geo.center().y())
        overlay.covers_changed.connect(self.setVisible)

    def mousePressEvent(self, _):
        self.overlay.hide_covers = not self.overlay.hide_covers
        self.overlay.update()
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(30, 90, 200, 120 if self.overlay.hide_covers else 220))
        p.drawEllipse(self.rect().adjusted(2, 2, -2, -2))
        p.setPen(Qt.white)
        f = QFont("Microsoft JhengHei UI")
        f.setPixelSize(18)
        p.setFont(f)
        p.drawText(self.rect(), Qt.AlignCenter, "譯")


class CaptionOverlay(QWidget):
    """Click-through strip at the bottom of the screen listing what was just heard and its translation."""
    MAX_LINES = 4
    LIFETIME = 25.0  # seconds a line stays up

    def __init__(self, screen):
        super().__init__()
        self.setWindowFlags(
            Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool | Qt.WindowTransparentForInput)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        geo = screen.availableGeometry()
        self.width_px = int(geo.width() * 0.7)
        self.setGeometry(geo.x() + (geo.width() - self.width_px) // 2, geo.y() + geo.height() - 340,
                         self.width_px, 330)
        self.lines = []  # (time, said, translation)
        self.live = None  # (said, translation) of the sentence still being spoken
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._expire)
        self.timer.start(1000)

    def add(self, said, translation):
        """A finished sentence: it replaces the live line."""
        self.live = None
        self.lines = (self.lines + [(time.monotonic(), said, translation)])[-self.MAX_LINES:]
        self.show()
        self.update()

    def set_live(self, said, translation):
        """The sentence so far, updated as it is spoken ('' removes it)."""
        self.live = (said, translation) if said else None
        if self.live:
            self.show()
        elif not self.lines:
            self.hide()
        self.update()

    def clear(self):
        self.lines = []
        self.live = None
        self.hide()

    def _expire(self):
        keep = [l for l in self.lines if time.monotonic() - l[0] < self.LIFETIME]
        if len(keep) != len(self.lines):
            self.lines = keep
            if not keep and not self.live:
                self.hide()
            self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)
        said_font, tr_font = QFont("Microsoft JhengHei UI"), QFont("Microsoft JhengHei UI")
        said_font.setPixelSize(15)
        tr_font.setPixelSize(22)
        inner = self.width_px - 24
        y = self.height() - 6
        shown = [(said, translation) for _t, said, translation in self.lines]
        if self.live:
            shown.append(self.live)  # the sentence being spoken is the newest line, at the bottom
        for said, translation in reversed(shown):
            rows = [(translation, tr_font, QColor(255, 235, 140)), (said, said_font, QColor(200, 200, 200))]
            rows = [(t, f, c) for t, f, c in rows if t]
            heights = [QFontMetricsF(f).boundingRect(QRectF(0, 0, inner, 10000), int(Qt.TextWordWrap), t).height()
                       for t, f, _c in rows]
            box = sum(heights) + 12
            top = y - box
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(20, 20, 20, 225))
            p.drawRoundedRect(QRectF(0, top, self.width_px, box), 6, 6)
            row_top = top + 6
            for (t, f, c), h in zip(rows, heights):
                p.setFont(f)
                p.setPen(c)
                p.drawText(QRectF(12, row_top, inner, h), Qt.AlignLeft | Qt.TextWordWrap, t)
                row_top += h
            y = top - 6

    def set_capture_hidden(self, hidden):
        ctypes.windll.user32.SetWindowDisplayAffinity(
            int(self.winId()), WDA_EXCLUDEFROMCAPTURE if hidden else 0)
