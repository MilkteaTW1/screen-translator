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
