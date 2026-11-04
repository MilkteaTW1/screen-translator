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


def test_a_cover_takes_the_colour_of_the_page_it_hides_and_readable_ink():
    import numpy as np
    app = QApplication.instance() or QApplication([])
    for page, ink_is_dark in (((250, 244, 230), True), ((30, 40, 60), False)):
        ov = Overlay(app.primaryScreen())
        ov.scale = 1.0
        ov.setGeometry(0, 0, 800, 600)
        noisy = np.tile([0, 255], (150, 100))  # no room beside the text: it gets covered
        colors = np.zeros((150, 200, 3), dtype=np.uint8)
        colors[:] = page
        colors[::2, ::3] = (0, 0, 0)  # the letters: a minority that must not tint the cover
        ov.set_background(noisy.astype(np.int16), (0, 0), colors)
        ov.set_items([(100, 300, 400, 40, "翻譯", 20)])
        img = QImage(800, 600, QImage.Format_ARGB32)  # kept alive while painting
        p = QPainter(img)
        ov.draw(p)
        p.end()
        fill, ink = ov.looks["翻譯"]
        assert ov.modes["翻譯"] == "cover"
        assert (fill.red(), fill.green(), fill.blue()) == page
        assert (ink.red() < 128) == ink_is_dark


def test_a_cover_stays_within_the_width_of_the_text_it_covers():
    from PySide6.QtCore import QRectF
    app = QApplication.instance() or QApplication([])
    ov = Overlay(app.primaryScreen())
    ov.scale = 1.0
    ov.setGeometry(0, 0, 1600, 600)
    long = "這是一段很長很長的翻譯文字，比原文所佔的寬度還要長許多，所以應該縮小字體或是換行，而不是向旁邊伸出去。" * 2
    ov.modes[long] = "cover"
    rect, font = ov._box(long, QRectF(100, 100, 300, 40), 20, "cover")
    assert rect.width() <= 300 * 1.04 + 0.5
    assert rect.x() == 100 and font.pixelSize() >= 12
