# Screen Translator

A free, fully offline screen translator for Windows. It reads the text on your screen with the built-in
Windows OCR, translates it locally with [Argos Translate](https://github.com/argosopentech/argos-translate),
and draws the translation in a click-through overlay directly **above** each text block, centred on it.
Nothing is sent over the network and your normal use of the computer is not disturbed.

## Features

- Pick the screen language and the target language in the settings window.
- Proper nouns are never translated: a do-not-translate list plus automatic detection
  (capitalised mid-sentence words, ALL CAPS, CamelCase, optional katakana).
- Wrapped lines are merged into sentences (split on `. ! ?`), so paragraphs are translated as a whole.
- Stable overlay: a block must be seen twice before it is shown, tracked blocks keep their position,
  and the translation box is placed only from its own block (never re-chosen from its surroundings).
- The overlay and settings window are excluded from screen capture, so the app never re-translates itself
  (a tray option lets screenshots include translations).
- Configurable refresh interval (0 s and up; the real limit is OCR speed).

## Requirements

- Windows 10/11
- Python 3.10 - 3.12
- Windows OCR language pack for the screen language (Settings > Time & language > Language & region)

## Install and run

```bat
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python scripts\download_packs.py en>zt     :: example: English -> Traditional Chinese
run.bat
```

Argos language packs are downloaded once (about 50-100 MB each) and then work offline.
Pairs that do not involve English go through English, so `ja>zt` needs `ja>en` and `en>zt`.
Argos codes: `zh` = Simplified Chinese, `zt` = Traditional Chinese.

Closing the settings window quits the app. Settings are stored in `%APPDATA%\ScreenTranslator\settings.json`.
The hidden `region` setting (`[left, top, width, height]`) limits scanning to part of the screen.

## Build a standalone exe

```bat
.venv\Scripts\pip install -r requirements-dev.txt
build.bat
```

The result is `dist\ScreenTranslator\`. The exe build is large (Qt and Argos) and has not been tested
on many machines; see [docs/KNOWN_ISSUES.md](docs/KNOWN_ISSUES.md).

## Development

```bat
.venv\Scripts\pip install -r requirements-dev.txt
.venv\Scripts\python -m pytest
```

See [CONTRIBUTING.md](CONTRIBUTING.md) and [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).
Help is wanted on everything in [docs/KNOWN_ISSUES.md](docs/KNOWN_ISSUES.md).

## License

MIT
