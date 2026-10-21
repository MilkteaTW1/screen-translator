import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

# Qt has to be loaded before the winrt packages (imported by screen_translator.ocr), otherwise
# the process crashes with an access violation on Windows.
import PySide6.QtWidgets  # noqa: F401,E402
