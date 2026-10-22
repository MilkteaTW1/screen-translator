# Contributing

1. Fork, create a venv and install `requirements.txt` and `requirements-dev.txt`.
2. Run `python -m pytest` before opening a pull request; add tests for filters and layout changes.
3. The app is Windows-only (Windows OCR, `SetWindowDisplayAffinity`). Do not test on your own
   working screen with long sessions; the optional `region` setting limits scanning to a test window.
4. Keep code style consistent with the existing modules (short functions, comments that explain why).

Interface translations are plain JSON files in `src/screen_translator/locales/` (see the README there); no code changes
are needed to add a language.

Import order matters: `PySide6` must be imported before the `winrt` packages (done in `app.py`
and `tests/conftest.py`), otherwise the process crashes with an access violation.
