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
