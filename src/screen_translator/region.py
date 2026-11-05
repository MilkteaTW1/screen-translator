"""Drag a rectangle on the screen to choose the only part that is translated (subtitles, a game's dialogue box)."""
from PySide6.QtCore import QPoint, QRect, Qt, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QWidget

from .plat import IS_MAC
from .i18n import t


class RegionPicker(QWidget):
    picked = Signal(list)  # [left, top, width, height] in the pixels the screen is captured in
    MIN = 20

    def __init__(self, screen):
        super().__init__()
        self.screen_ = screen
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setCursor(Qt.CrossCursor)
        self.setGeometry(screen.geometry())
        self.start = self.end = None

    def begin(self):
        self.start = self.end = None
        self.show()
        self.raise_()
        self.activateWindow()
        self.setFocus()

    def selection(self):
        if self.start is None:
            return QRect()
        return QRect(self.start, self.end).normalized()

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.start = self.end = e.position().toPoint()
        else:
            self.hide()

    def mouseMoveEvent(self, e):
        if self.start is not None:
            self.end = e.position().toPoint()
            self.update()

    def mouseReleaseEvent(self, e):
        if e.button() != Qt.LeftButton or self.start is None:
            return
        self.end = e.position().toPoint()
        r = self.selection()
        self.hide()
        if r.width() >= self.MIN and r.height() >= self.MIN:
            geo = self.screen_.geometry()
            k = 1.0 if IS_MAC else self.screen_.devicePixelRatio()  # macOS captures in points, Windows in pixels
            self.picked.emit([round((geo.x() + r.x()) * k), round((geo.y() + r.y()) * k),
                              round((r.width() - 1) * k), round((r.height() - 1) * k)])

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape:
            self.hide()

    def paintEvent(self, _):
        p = QPainter(self)
        p.fillRect(0, 0, self.width(), self.height(), QColor(0, 0, 0, 90))
        r = self.selection()
        if r.isValid() and not r.isNull():
            p.setCompositionMode(QPainter.CompositionMode_Clear)
            p.fillRect(r, Qt.transparent)
            p.setCompositionMode(QPainter.CompositionMode_SourceOver)
            p.setPen(QColor(60, 140, 255))
            p.drawRect(r)
        else:
            p.setPen(Qt.white)
            p.drawText(QRect(0, 0, self.width(), 80), Qt.AlignCenter, t("region_hint"))
