# Contributing to Screen Translator / 參與貢獻

Thanks for helping! Bug fixes, new interface languages and small improvements are all welcome.
歡迎修正錯誤、新增介面語言與各種小改進。

## Easiest way in: add your language

The interface is one JSON file per language. No coding needed: follow
[src/screen_translator/locales/README.md](src/screen_translator/locales/README.md) and open a pull request.
See the issue [Add your language](https://github.com/MilkteaTW1/screen-translator/issues/38); comment there so two people do not take the same language.

## Quick start (Windows or macOS)

```bash
git clone https://github.com/<you>/screen-translator   # your fork
cd screen-translator
python -m venv .venv
.venv\Scripts\pip install -r requirements-dev.txt       # macOS/Linux: .venv/bin/pip
.venv\Scripts\python -m pytest                          # all tests should pass
.venv\Scripts\python scripts\launch.py                  # run the app
```

Python 3.10 - 3.12. Offline language packs are downloaded when you pick a language (see the README).

## Pull requests

- One change per pull request, on a branch of your fork. Mention `Closes #<issue>` if it fixes one.
- Add or extend a test in `tests/` for what you change. CI runs the tests on Windows and macOS.
- Interface text goes through `src/screen_translator/locales/*.json` (English and Traditional Chinese); do not hard-code strings in the code.
- Keep the code style of the existing modules (short functions, comments that explain why).
- Import order matters on Windows: `PySide6` must be imported before the `winrt` packages (done in `app.py` and `tests/conftest.py`), otherwise the process crashes with an access violation.
- Do not test on your own working screen for long sessions; the `region` setting limits scanning to a test window.
- The phone app is in `android/` (Kotlin); its unit tests run with Gradle (`:app:testDebugUnitTest`).
- The maintainer makes the releases; a merged change reaches users with the next one.

## Reporting bugs

Use the bug report form. Please say the version, your system, and what "does not work" means (does not open, Start does nothing, or no translation appears).
Security problems: see [SECURITY.md](SECURITY.md), not a public issue.
