import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QImage, QPainter
from PySide6.QtWidgets import QApplication

from screen_translator.overlay import Overlay


def test_translation_sits_above_block_and_centred():
    app = QApplication.instance() or QApplication([])
    ov = Overlay(app.primaryScreen())
    ov.scale = 1.0
    ov.setGeometry(0, 0, 800, 600)
    ov.set_items([(100, 300, 400, 40, "翻譯", 20)])
    img = QImage(800, 600, QImage.Format_ARGB32)
    p = QPainter(img)
    ov.draw(p)
    p.end()
    box = ov.drawn["翻譯"]
    assert box.bottom() <= 300
    assert abs(box.center().x() - 300) < 1
