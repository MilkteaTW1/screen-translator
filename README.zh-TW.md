# Screen Translator 螢幕翻譯

[English](README.md) | **繁體中文**

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
- 可自訂刷新間隔(0 秒起,實際速度受 OCR 速度限制)。

## 系統需求

- Windows 10 / 11
- Python 3.10 ~ 3.12(從原始碼執行時)
- Windows 已安裝螢幕語言的 OCR 語言包(設定 > 時間與語言 > 語言與區域)

## 下載

到 [Releases](../../releases) 下載 `ScreenTranslator-windows.zip`,解壓縮後執行 `ScreenTranslator.exe`。

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
