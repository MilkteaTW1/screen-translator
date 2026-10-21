# Screen Translator

**English** | [繁體中文](#screen-translator-螢幕翻譯)

A free, fully offline screen translator for Windows. It reads the text on your screen with the built-in
Windows OCR, translates it locally with [Argos Translate](https://github.com/argosopentech/argos-translate),
and draws the translation in a click-through overlay directly **above** each text block, centred on it.
Nothing is sent over the network and your normal use of the computer is not disturbed.

## Features

- Pick the screen language and the target language in the settings window. Missing offline language
  packs are offered for download right when you pick a language (you confirm first).
- Proper nouns are never translated: a do-not-translate list plus automatic detection
  (capitalised mid-sentence words, ALL CAPS, CamelCase, optional katakana).
- Wrapped lines are merged into sentences (split on `. ! ?`), so paragraphs are translated as a whole.
- Stable overlay: a block must be seen twice before it is shown, tracked blocks keep their position,
  and the translation box is placed only from its own block (never re-chosen from its surroundings).
- The overlay and settings window are excluded from screen capture, so the app never re-translates itself
  (a tray option lets screenshots include translations).
- Light on resources: runs at below-normal priority, 2 translation threads, no torch/spacy; starts in about a second
  and can start with Windows, minimised to the tray, translating right away.
- Optional better quality: point it at a local LLM server (Ollama, LM Studio...) in the settings; falls back to
  the built-in model when the server is not running.
- Configurable refresh interval (0 s and up; the real limit is OCR speed).

## Requirements

- Windows 10/11
- Python 3.10 - 3.12
- Windows OCR language pack for the screen language (Settings > Time & language > Language & region)

## Download

Download `ScreenTranslator-Setup-x.y.z.exe` from the [Releases](../../releases) page and run it (about 70 MB, no admin
rights needed; an optional task starts it with Windows). Language packs are **not** bundled: the app asks before
downloading each one (50-100 MB), or you can import `.argosmodel` files you already have.

## Install and run from source

```bat
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python scripts\download_packs.py en>zt     :: example: English -> Traditional Chinese
run.bat
```

The app also asks to download missing packs when you choose a language. Argos language packs are downloaded once (about 50-100 MB each) and then work offline.
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

---

# Screen Translator 螢幕翻譯

[English](#screen-translator) | **繁體中文**

免費、完全離線的 Windows 螢幕翻譯工具。它用 Windows 內建 OCR 讀取螢幕上的文字,
再用 [Argos Translate](https://github.com/argosopentech/argos-translate) 在本機翻譯,
並把譯文顯示在每個文字區塊的**正上方**(水平置中)。整個過程不連網,
半透明覆蓋層可點穿,不影響你平常操作電腦。

## 功能

- 在設定視窗自選螢幕上的語言與要翻譯成的語言。選語言時如果缺少離線語言包,
  會先詢問你,同意後才下載。
- 專有名詞不翻譯:可自訂「不翻譯清單」,也會自動偵測(句中大寫開頭、全大寫、CamelCase、可選的片假名)。
- 依句號、問號、驚嘆號判斷句子,被視窗邊框切斷的換行會合併成完整句子再翻譯。
- 畫面穩定:文字區塊要連續看到兩次才顯示,已追蹤的區塊會固定位置,
  譯文位置只由自己的區塊決定,不會在上下左右之間跳來跳去。
- 覆蓋層與設定視窗不會被截圖拍到,所以不會翻譯到自己的譯文(托盤選單可改成讓截圖包含譯文)。
- 低資源:以低優先權執行、翻譯只用 2 個執行緒、不含 torch/spacy,約一秒啟動,
  可開機自動啟動並縮小到系統匣、啟動即開始翻譯。
- 可選的更高品質:在設定中指定本機 LLM 伺服器(Ollama、LM Studio 等),伺服器沒開時自動退回內建模型。
- 可自訂刷新間隔(0 秒起,實際速度受 OCR 速度限制)。

## 系統需求

- Windows 10 / 11
- Python 3.10 ~ 3.12(從原始碼執行時)
- Windows 已安裝螢幕語言的 OCR 語言包(設定 > 時間與語言 > 語言與區域)

## 下載

到 [Releases](../../releases) 下載 `ScreenTranslator-Setup-x.y.z.exe` 並執行(約 70 MB,不需要系統管理員權限,
可勾選開機自動啟動)。語言包不包含在安裝檔裡:選語言時程式會先詢問再下載(每個 50~100 MB),
也可以匯入你已經有的 `.argosmodel` 檔。

## 從原始碼執行

```bat
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
run.bat
```

第一次選語言時程式會詢問是否下載離線語言包(每個約 50~100 MB,只需下載一次)。
也可以手動下載:`.venv\Scripts\python scripts\download_packs.py en>zt`。
不含英文的語言對會經由英文轉譯,例如 `ja>zt` 需要 `ja>en` 與 `en>zt`。
Argos 代碼:`zh` = 簡體中文、`zt` = 繁體中文。

按設定視窗的 X 會關閉整個程式。設定檔存放在 `%APPDATA%\ScreenTranslator\settings.json`。
隱藏設定 `region`(`[左, 上, 寬, 高]`)可以限制只掃描螢幕的一部分。

## 開發

```bat
.venv\Scripts\pip install -r requirements-dev.txt
.venv\Scripts\python -m pytest
build.bat
```

詳見 [CONTRIBUTING.md](CONTRIBUTING.md)、[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)。
歡迎協助 [docs/KNOWN_ISSUES.md](docs/KNOWN_ISSUES.md) 裡列出的問題。

## 授權

MIT
