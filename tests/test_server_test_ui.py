import time

from PySide6.QtWidgets import QApplication

from screen_translator import app as appmod


class _Overlay:
    def __getattr__(self, name):
        return lambda *a, **k: None


def _panel(monkeypatch, tmp_path):
    qapp = QApplication.instance() or QApplication([])
    monkeypatch.setattr(appmod, "SETTINGS_PATH", tmp_path / "settings.json")
    panel = appmod.Panel(appmod.Worker(appmod.LANGUAGES), _Overlay(), appmod.LANGUAGES)
    return qapp, panel


def _wait(qapp, until, seconds=3.0):
    end = time.monotonic() + seconds
    while time.monotonic() < end and not until():
        qapp.processEvents()
        time.sleep(0.01)
    assert until()


def test_a_working_key_shows_a_green_tick(monkeypatch, tmp_path):
    qapp, panel = _panel(monkeypatch, tmp_path)
    monkeypatch.setattr(appmod, "check_server", lambda settings, target="zh-TW": (True, "你好,世界。"))
    panel._select(panel.server_kind, "gemini")
    panel.server_key.setText("AIza-test")  # typed or pasted: tested by itself a moment later
    assert panel._server_timer.isActive()
    _wait(qapp, lambda: panel.server_test_label.text().startswith("✓"))
    assert "你好,世界。" in panel.server_test_label.text()
    assert "#2e9e5b" in panel.server_test_label.styleSheet()  # green


def test_a_bad_key_shows_a_red_cross_with_the_reason(monkeypatch, tmp_path):
    qapp, panel = _panel(monkeypatch, tmp_path)
    monkeypatch.setattr(appmod, "check_server", lambda settings, target="zh-TW": (False, "HTTP 400 API key not valid"))
    panel._select(panel.server_kind, "deepl")
    panel.server_key.setText("wrong")
    _wait(qapp, lambda: panel.server_test_label.text().startswith("✗"))
    assert "API key not valid" in panel.server_test_label.text()
    assert "#d64545" in panel.server_test_label.styleSheet()  # red


def test_an_answer_for_a_key_that_was_changed_since_is_dropped(monkeypatch, tmp_path):
    qapp, panel = _panel(monkeypatch, tmp_path)
    panel._select(panel.server_kind, "deepl")
    panel.server_key.setText("first")
    old = panel._server_test_id
    panel.server_key.setText("second")  # typed on: the first test no longer says anything about this key
    panel.server_tested.emit(old, True, "late")
    qapp.processEvents()
    assert "late" not in panel.server_test_label.text()


def test_nothing_is_tested_without_a_server_or_before_a_key_is_entered(monkeypatch, tmp_path):
    qapp, panel = _panel(monkeypatch, tmp_path)
    calls = []
    monkeypatch.setattr(appmod, "check_server", lambda *a, **k: calls.append(1) or (True, "x"))
    panel._select(panel.server_kind, "off")
    panel._test_server_now()
    assert panel.server_test_label.text() == "" and not calls
    panel._select(panel.server_kind, "gemini")  # a kind, but no key yet
    panel._test_server_now()
    assert not calls and panel.server_test_label.text() == "Fill in the address or key to test it"


def test_the_spoken_language_list_has_more_than_english_and_chinese(monkeypatch, tmp_path):
    _qapp, panel = _panel(monkeypatch, tmp_path)
    codes = {panel.speech_lang.itemData(i) for i in range(panel.speech_lang.count())}
    assert codes >= {"auto", "en", "zh", "ja", "ko", "fr", "de", "es", "ru", "nl", "pl", "tr", "hi", "uk"}


def test_caption_settings_are_applied_and_kept_in_range(monkeypatch, tmp_path):
    from screen_translator.overlay import CaptionOverlay, caption_look
    qapp, panel = _panel(monkeypatch, tmp_path)
    panel.captions = CaptionOverlay(qapp.primaryScreen())
    panel.caption_width.setValue(50)
    panel.caption_font.setValue(44)
    panel._select(panel.caption_position, "top")
    assert panel.captions.look["caption_width"] == 50 and panel.captions.look["caption_font"] == 44
    assert panel.captions.look["caption_position"] == "top" and panel.captions.sample is not None  # a sample is shown
    geo = qapp.primaryScreen().availableGeometry()
    assert panel.captions.width() == int(geo.width() * 0.5) and panel.captions.y() == geo.y() + 10
    assert panel.current()["caption_font"] == 44  # and saved
    # a hand-edited settings file cannot break the strip
    assert caption_look({"caption_width": 5000, "caption_font": "huge", "caption_position": "middle", "caption_lines": 0}) == {
        "caption_width": 100, "caption_font": 30, "caption_opacity": 88, "caption_position": "bottom",
        "caption_lines": 1, "caption_show_said": True}
