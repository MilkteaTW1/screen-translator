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


def _draw(luma):
    import numpy as np
    app = QApplication.instance() or QApplication([])
    ov = Overlay(app.primaryScreen())
    ov.scale = 1.0
    ov.setGeometry(0, 0, 800, 600)
    ov.set_background(np.array(luma, dtype=np.int16))
    ov.set_items([(100, 300, 400, 40, "翻譯", 20)])
    img = QImage(800, 600, QImage.Format_ARGB32)
    p = QPainter(img)
    ov.draw(p)
    p.end()
    return ov


def test_empty_space_of_any_colour_is_used():
    import numpy as np
    ov = _draw(np.full((150, 200), 70))  # a flat dark-grey screen
    assert ov.modes["翻譯"] == "above"


def test_text_all_around_means_the_translation_covers_it():
    import numpy as np
    noisy = np.tile([0, 255], (150, 100))  # text everywhere
    ov = _draw(noisy)
    assert ov.modes["翻譯"] == "cover"
    assert ov.drawn["翻譯"].top() == 300
