import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QImage, QPainter
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from screen_translator.overlay import Overlay
from screen_translator.region import RegionPicker
from screen_translator.translator import _deepl_code, server_from_settings, server_translate_group


def _overlay():
    app = QApplication.instance() or QApplication([])
    ov = Overlay(app.primaryScreen())
    ov.scale = 1.0
    ov.setGeometry(0, 0, 800, 600)
    ov.set_items([(100, 300, 400, 40, "譯一", 20), (100, 100, 400, 40, "譯二", 20)])
    return ov


def _paint(ov):
    img = QImage(800, 600, QImage.Format_ARGB32)
    p = QPainter(img)
    ov.draw(p)
    p.end()


def test_hover_mode_draws_only_the_block_under_the_mouse():
    ov = _overlay()
    ov.hover = True
    ov.cursor_pos = lambda: QPoint(300, 320)  # on the first block
    _paint(ov)
    assert len(ov.painted) == 1 and ov.painted[0][1] > 200
    ov.cursor_pos = lambda: QPoint(700, 560)  # on nothing
    _paint(ov)
    assert ov.painted == []


def test_without_hover_mode_every_translation_is_drawn():
    ov = _overlay()
    ov.cursor_pos = lambda: QPoint(700, 560)
    _paint(ov)
    assert len(ov.painted) == 2


def test_the_hide_shortcut_hides_everything_and_shows_it_again():
    ov = _overlay()
    ov.set_suppressed(True)
    _paint(ov)
    assert ov.painted == []
    ov.set_suppressed(False)
    _paint(ov)
    assert len(ov.painted) == 2


def test_dragging_a_rectangle_picks_a_region_in_capture_pixels():
    app = QApplication.instance() or QApplication([])
    picker = RegionPicker(app.primaryScreen())
    picker.setGeometry(0, 0, 800, 600)
    got = []
    picker.picked.connect(got.append)
    picker.begin()
    QTest.mousePress(picker, Qt.LeftButton, Qt.NoModifier, QPoint(100, 50))
    QTest.mouseMove(picker, QPoint(300, 150))
    QTest.mouseRelease(picker, Qt.LeftButton, Qt.NoModifier, QPoint(300, 150))
    from screen_translator.plat import IS_MAC
    k = 1.0 if IS_MAC else app.primaryScreen().devicePixelRatio()
    assert got == [[round(100 * k), round(50 * k), round(200 * k), round(100 * k)]]


def test_a_tiny_drag_or_escape_picks_nothing():
    app = QApplication.instance() or QApplication([])
    picker = RegionPicker(app.primaryScreen())
    picker.setGeometry(0, 0, 800, 600)
    got = []
    picker.picked.connect(got.append)
    picker.begin()
    QTest.mousePress(picker, Qt.LeftButton, Qt.NoModifier, QPoint(10, 10))
    QTest.mouseRelease(picker, Qt.LeftButton, Qt.NoModifier, QPoint(12, 12))
    picker.begin()
    QTest.keyClick(picker, Qt.Key_Escape)
    assert got == [] and not picker.isVisible()


def test_the_shortcut_letters_are_read_from_a_character_or_a_windows_key_code():
    from types import SimpleNamespace as K
    from screen_translator.hotkeys import Hotkeys
    assert Hotkeys.letter(K(char="T")) == "t" and Hotkeys.letter(K(char=None, vk=84)) == "t"
    assert Hotkeys.letter(K(char=None, vk=13)) is None and Hotkeys.letter(K(name="ctrl_l")) is None
    keys = Hotkeys()
    seen = []
    keys.toggle.connect(lambda: seen.append("toggle"))
    keys.hide.connect(lambda: seen.append("hide"))
    keys.region.connect(lambda: seen.append("region"))
    for letter, fn in keys.handlers().items():
        fn()
    assert seen == ["toggle", "hide", "region"]


class _DeepL(BaseHTTPRequestHandler):
    seen = {}

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        _DeepL.seen = {"auth": self.headers["Authorization"], "path": self.path, "body": body}
        data = json.dumps({"translations": [{"text": "譯:" + s} for s in body["text"]]}).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *a):
        pass


def test_deepl_gets_its_own_key_header_and_language_names():
    httpd = HTTPServer(("127.0.0.1", 0), _DeepL)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        server = {"kind": "deepl", "url": f"http://127.0.0.1:{httpd.server_port}", "key": "k:fx"}
        assert server_translate_group(server, ["Hello", "Bye"], "en", "zh-TW") == ["譯:Hello", "譯:Bye"]
        seen = _DeepL.seen
        assert seen["auth"] == "DeepL-Auth-Key k:fx" and seen["path"] == "/v2/translate"
        assert seen["body"]["target_lang"] == "ZH-HANT" and seen["body"]["source_lang"] == "EN"
    finally:
        httpd.shutdown()


def test_deepl_free_keys_use_the_free_address_and_codes_map():
    free = server_from_settings({"server_kind": "deepl", "server_key": "abc:fx"})
    paid = server_from_settings({"server_kind": "deepl", "server_key": "abc"})
    assert "api-free" in free["url"] and "api-free" not in paid["url"] and free["first"]
    assert server_from_settings({"server_kind": "deepl", "server_key": " "}) is None
    assert (_deepl_code("en", True), _deepl_code("pt", True), _deepl_code("zh-CN", False), _deepl_code("ja", True)) == (
        "EN-US", "PT-BR", "ZH", "JA")


def test_cover_all_lays_every_translation_over_its_text():
    ov = _overlay()
    ov.set_cover_all(True)
    _paint(ov)
    assert set(ov.modes.values()) == {"cover"}
    assert ov.drawn["譯一"].top() == 300 and ov.drawn["譯二"].top() == 100


def _rect(x, w, y=0):
    from PySide6.QtCore import QRectF
    return QRectF(x, y, w, 20)


def test_alignment_follows_the_neighbouring_blocks():
    f = Overlay._align
    assert f(_rect(100, 300), 20, [_rect(100, 200, 25), _rect(100, 250, -25)]) == "left"
    assert f(_rect(200, 200), 20, [_rect(150, 300, 25), _rect(250, 100, -25)]) == "center"
    assert f(_rect(300, 100), 20, [_rect(200, 200, 25), _rect(250, 150, -25)]) == "right"
    assert f(_rect(300, 100), 20, []) == "left"
    assert f(_rect(300, 100), 20, [_rect(300, 100, 900)]) == "left"  # too far away to line up with
