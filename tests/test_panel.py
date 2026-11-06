from PySide6.QtWidgets import QApplication, QMessageBox

from screen_translator import app as appmod


class _Overlay:
    def set_items(self, items):
        pass

    def set_motion(self, vx, vy):
        pass

    def set_capture_hidden(self, hidden):
        pass

    def set_hover(self, on):
        pass

    def set_cover_all(self, on):
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


def test_translations_can_be_hidden_while_the_page_scrolls_and_come_back_when_it_stops():
    import time
    QApplication.instance() or QApplication([])
    worker = appmod.Worker(appmod.LANGUAGES)
    worker.tracks = [{"x": 10, "y": 20, "w": 300, "h": 30, "lh": 20, "seen": 2, "done": True, "translation": "你好"}]
    worker.scrolling_until = time.monotonic() + 5  # the page is moving
    for hide, shown in ((False, "你好"), (True, None)):
        worker.settings = {**worker.settings, "hide_on_scroll": hide}
        assert [i[4] for i in worker._snapshot()] == [shown]
    worker.scrolling_until = 0.0  # it stopped
    assert [i[4] for i in worker._snapshot()] == ["你好"]


def _closing(monkeypatch):
    from PySide6.QtWidgets import QSystemTrayIcon
    QApplication.instance() or QApplication([])
    monkeypatch.setattr(QSystemTrayIcon, "isSystemTrayAvailable", staticmethod(lambda: True))
    quits = []
    monkeypatch.setattr(appmod.QApplication, "quit", staticmethod(lambda: quits.append(1)))
    panel = appmod.Panel(appmod.Worker(appmod.LANGUAGES), _Overlay(), appmod.LANGUAGES)
    hidden = []
    panel.hidden_to_tray.connect(lambda: hidden.append(1))
    return panel, hidden, quits


def test_the_x_button_asks_the_first_time_and_remembers_the_answer(monkeypatch):
    from PySide6.QtGui import QCloseEvent
    panel, hidden, quits = _closing(monkeypatch)
    answers = iter(["tray"])
    monkeypatch.setattr(panel, "_ask_close", lambda: next(answers))
    assert panel.close_action.currentData() == "ask"
    event = QCloseEvent()
    panel.closeEvent(event)
    assert not event.isAccepted() and hidden == [1] and quits == []
    assert panel.close_action.currentData() == "tray"  # remembered
    event = QCloseEvent()
    panel.closeEvent(event)  # no question the second time
    assert not event.isAccepted() and hidden == [1, 1]


def test_choosing_to_quit_everything_quits_and_cancelling_does_nothing(monkeypatch):
    from PySide6.QtGui import QCloseEvent
    panel, hidden, quits = _closing(monkeypatch)
    monkeypatch.setattr(panel, "_ask_close", lambda: None)  # cancel
    event = QCloseEvent()
    panel.closeEvent(event)
    assert not event.isAccepted() and hidden == [] and quits == [] and panel.close_action.currentData() == "ask"
    monkeypatch.setattr(panel, "_ask_close", lambda: "quit")
    event = QCloseEvent()
    panel.closeEvent(event)
    assert event.isAccepted() and quits == [1]


def test_the_user_is_told_once_per_kind_of_trouble_and_again_after_it_worked_in_between():
    QApplication.instance() or QApplication([])
    worker = appmod.Worker(appmod.LANGUAGES)
    told = []
    worker.problem.connect(told.append)
    worker.translator.unserved = True
    worker.translator.google = True
    worker.translator._google_down, worker.translator._limits = 1e12, 1
    for _ in range(5):  # the same trouble on every scan: one message
        worker._report_problem()
    assert len(told) == 1 and "Google" in told[0]
    worker.translator.unserved = False  # it worked
    worker._report_problem()
    worker.translator.unserved = True
    worker._report_problem()
    assert len(told) == 2


def test_one_ocr_language_shows_how_to_add_more(monkeypatch, tmp_path):
    qapp = QApplication.instance() or QApplication([])
    monkeypatch.setattr(appmod, "SETTINGS_PATH", tmp_path / "settings.json")
    monkeypatch.setattr(appmod, "set_autostart", lambda on: None)
    monkeypatch.setattr(appmod, "IS_WIN", True)
    monkeypatch.setattr(appmod.ocr, "available_languages", lambda: [("zh-Hant-TW", "Chinese")])
    panel = appmod.Panel(appmod.Worker(appmod.LANGUAGES), _Overlay(), appmod.LANGUAGES)
    assert not panel.ocr_hint.isHidden()
    monkeypatch.setattr(appmod.ocr, "available_languages", lambda: [("en-US", "English"), ("ja", "Japanese")])
    panel = appmod.Panel(appmod.Worker(appmod.LANGUAGES), _Overlay(), appmod.LANGUAGES)
    assert panel.ocr_hint.isHidden()
