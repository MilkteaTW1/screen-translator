import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

# Qt has to be loaded before the winrt packages (imported by screen_translator.ocr), otherwise
# the process crashes with an access violation on Windows.
import PySide6.QtWidgets  # noqa: F401,E402

import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def english_interface():
    """Tests read interface text: start each one in English whatever language Windows is set to."""
    from screen_translator import i18n
    i18n.load("en")
    yield
    i18n.load("en")


@pytest.fixture(autouse=True)
def no_blocking_dialogs(monkeypatch):
    """A machine without the language packs asks to download them in a modal box; nobody is there to click it."""
    from PySide6.QtWidgets import QMessageBox
    monkeypatch.setattr(QMessageBox, "exec", lambda self: 0)


@pytest.fixture(autouse=True)
def no_real_translation_memory(monkeypatch, tmp_path):
    """Tests never read or write the translations remembered on this machine."""
    from screen_translator import app
    monkeypatch.setattr(app, "CACHE_PATH", tmp_path / "translations.jsonl")


@pytest.fixture(autouse=True)
def no_real_settings(monkeypatch, tmp_path):
    """Tests never read or write this machine's settings file (changing a switch in a test saves it)."""
    from screen_translator import app
    monkeypatch.setattr(app, "SETTINGS_PATH", tmp_path / "settings.json")
