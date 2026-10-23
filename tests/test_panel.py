from PySide6.QtWidgets import QApplication, QMessageBox

from screen_translator import app as appmod


class _Overlay:
    def set_items(self, items):
        pass

    def set_motion(self, vx, vy):
        pass

    def set_capture_hidden(self, hidden):
        pass


def test_declining_the_download_starts_nothing(monkeypatch, tmp_path):
    qapp = QApplication.instance() or QApplication([])
    monkeypatch.setattr(appmod, "missing_pairs", lambda s, d: [("en", "zt")])
    monkeypatch.setattr(QMessageBox, "exec", lambda self: 0)  # the user picks nothing: "Not now"
    monkeypatch.setattr(appmod, "SETTINGS_PATH", tmp_path / "settings.json")
    started = []
    monkeypatch.setattr(appmod.threading, "Thread", lambda **k: started.append(k))
    panel = appmod.Panel(appmod.Worker(appmod.LANGUAGES), _Overlay(), appmod.LANGUAGES)
    panel.ensure_packs()
    assert not started and not panel.downloading
    assert "en → zt" in panel.state.text()


def test_main_starts_and_quits(monkeypatch, tmp_path):
    """Runs main() for real: a signal or variable missing at start-up fails here, not on a user's PC."""
    qapp = QApplication.instance() or QApplication([])
    monkeypatch.setattr(appmod, "SETTINGS_PATH", tmp_path / "settings.json")
    monkeypatch.setattr(appmod.updater, "check", lambda: None)
    monkeypatch.setattr(appmod, "QApplication", lambda argv: qapp)
    monkeypatch.setattr(type(qapp), "exec", lambda self: 0)
    try:
        appmod.main()
    except SystemExit as e:
        assert e.code == 0


def test_scan_schedule():
    due = appmod.scan_due
    assert due(True, False, 5.0, 1.0)  # new content after a quiet spell: scan at once
    assert not due(True, False, 0.3, 1.0)  # constantly changing screen: limited by the interval setting
    assert not due(False, False, 99.0, 1.0)  # nothing changed: no scan
    assert due(False, True, appmod.CONFIRM_GAP, 5.0)  # text waiting for confirmation: short gap, not the interval
    assert not due(False, True, 0.01, 5.0)


def test_language_button_switches_every_label_and_is_remembered(monkeypatch, tmp_path):
    qapp = QApplication.instance() or QApplication([])
    monkeypatch.setattr(appmod, "SETTINGS_PATH", tmp_path / "settings.json")
    monkeypatch.setattr(appmod, "set_autostart", lambda on: None)
    panel = appmod.Panel(appmod.Worker(appmod.LANGUAGES), _Overlay(), appmod.LANGUAGES)
    assert panel.toggle.text() == "Start screen translation" and panel.tabs.tabText(0) == "Translate"
    panel._fill_language_menu()
    names = [a.text() for a in panel.language_button.menu().actions()]
    assert names[:2] == ["English", "繁體中文"]
    panel.set_language("zh-TW")
    assert panel.toggle.text() == "開始翻譯畫面" and panel.tabs.tabText(0) == "翻譯"
    assert "繁體中文" in panel.language_button.text()
    assert panel.skip_names.text().startswith("略過")
    assert panel.speech_source.itemText(1) == "麥克風"
    assert appmod.json.loads((tmp_path / "settings.json").read_text(encoding="utf-8"))["ui_language"] == "zh-TW"
    panel.set_language("en")
    assert panel.toggle.text() == "Start screen translation"


def test_screen_language_offers_auto_detect_and_asks_for_every_installed_language(monkeypatch, tmp_path):
    qapp = QApplication.instance() or QApplication([])
    monkeypatch.setattr(appmod, "SETTINGS_PATH", tmp_path / "settings.json")
    monkeypatch.setattr(appmod, "set_autostart", lambda on: None)
    monkeypatch.setattr(appmod.ocr, "available_languages", lambda: [("en-US", "English"), ("ja", "Japanese")])
    panel = appmod.Panel(appmod.Worker(appmod.LANGUAGES), _Overlay(), appmod.LANGUAGES)
    assert panel.source.itemData(0) == "auto" and panel.source.itemText(0) == "Auto-detect"
    panel._select(panel.source, "auto")
    assert panel.current()["source"] == "auto"
    assert panel._source_codes(panel.current()) == ["en", "ja"]
    panel.set_language("zh-TW")
    assert panel.source.itemText(0) == "自動偵測"


def test_screen_and_speech_translation_switch_on_and_off_independently(monkeypatch, tmp_path):
    qapp = QApplication.instance() or QApplication([])
    monkeypatch.setattr(appmod, "SETTINGS_PATH", tmp_path / "settings.json")
    monkeypatch.setattr(appmod, "set_autostart", lambda on: None)
    panel = appmod.Panel(appmod.Worker(appmod.LANGUAGES), _Overlay(), appmod.LANGUAGES)
    assert panel.toggle.text() == "Start screen translation" and panel.speech_toggle.text() == "Start speech translation"
    panel.speech_toggle.click()  # speech on: the screen side is untouched
    assert panel.speech_enabled.isChecked() and not panel.worker.running
    assert panel.speech_toggle.text() == "Stop speech translation" and panel.toggle.text() == "Start screen translation"
    panel.speech_toggle.click()
    assert not panel.speech_enabled.isChecked() and panel.speech_toggle.text() == "Start speech translation"
    assert appmod.json.loads((tmp_path / "settings.json").read_text(encoding="utf-8"))["speech_enabled"] is False


def test_a_paragraph_that_grows_while_it_scrolls_in_keeps_its_translation_until_the_new_one_is_ready():
    old = "If you are looking to improve your English conversational"
    assert appmod._grows(old, old + " skills or just trying to refine what you already know.")
    assert not appmod._grows(old, "Something else entirely, with no words in common here.")
    track = {"seen": 2, "done": False, "translation": None, "stale": "舊譯文"}
    assert appmod._visible(track) == "舊譯文"
    track.update(done=True, translation="新譯文")
    assert appmod._visible(track) == "新譯文"
    assert appmod._visible({**track, "seen": 1}) is None
