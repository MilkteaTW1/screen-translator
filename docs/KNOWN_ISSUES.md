# Known issues and ideas (good first issues)

- Offline translation quality is limited (small Argos models, long run-on text can loop).
- Usernames such as `Itz_adeel` lose the underscore in OCR and may be translated; add them to the glossary.
- Translations sit above their block and may cover the line above it (by design; no flipping).
- Scrolling: translations appear only after the page stops moving.
- Only the primary monitor is scanned; no UI for choosing a region (only the hidden `region` setting).
- English OCR cannot read Chinese text, so mixed-language screens can overlap.
- No global hotkeys (start/stop, toggle screenshots).
- The PyInstaller build is untested on clean machines; bundling Argos packs is not handled.
- No CI; a GitHub Actions workflow running `pytest` on Windows would help.
