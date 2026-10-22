from PySide6.QtWidgets import QApplication, QMessageBox

from screen_translator import app as appmod


class _Overlay:
    def set_items(self, items):
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
    assert panel.toggle.text() == "Start" and panel.tabs.tabText(0) == "Translate"
    panel._fill_language_menu()
    names = [a.text() for a in panel.language_button.menu().actions()]
    assert names[:2] == ["English", "繁體中文"]
    panel.set_language("zh-TW")
    assert panel.toggle.text() == "開始" and panel.tabs.tabText(0) == "翻譯"
    assert "繁體中文" in panel.language_button.text()
    assert panel.skip_names.text().startswith("略過")
    assert panel.speech_source.itemText(1) == "麥克風"
    assert appmod.json.loads((tmp_path / "settings.json").read_text(encoding="utf-8"))["ui_language"] == "zh-TW"
    panel.set_language("en")
    assert panel.toggle.text() == "Start"
