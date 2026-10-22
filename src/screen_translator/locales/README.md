# Interface translations

Every language is one file in this folder, named after its language tag (`en.json`, `zh-TW.json`, `ja.json`, `pt-BR.json` …).
The app starts in the language Windows is set to and can switch from the language button at the top of the window.

## Add or fix a language

1. Copy `en.json` to `<tag>.json`, for example `ja.json`.
2. Set `"_name"` to the language's name written in that language (shown in the language menu), for example `"日本語"`.
3. Translate the values. Do not change the keys on the left.
4. Keep `{placeholders}` such as `{names}`, `{pct}` or `{err}` exactly as they are; they are filled in by the app.
   `\n` is a line break.
5. Open a pull request with the file. Missing keys fall back to English, so a partial translation is fine.

You can try a file without rebuilding anything: copy it to `%APPDATA%\ScreenTranslator\locales\` and restart the app.
A file there replaces a built-in one with the same name.

`tests/test_i18n.py` checks that every file is valid JSON and that its placeholders match `en.json`.
