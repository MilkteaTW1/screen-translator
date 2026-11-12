# 推廣素材(草稿,尚未發布)

這個資料夾只放草稿。發文、上架、回覆留言都要由你本人決定和操作。

| 檔案 | 內容 |
| --- | --- |
| [product-hunt.md](product-hunt.md) | Product Hunt:名稱、tagline、描述、首則 maker comment、圖片清單 |
| [social-posts.md](social-posts.md) | Twitter/X 3 則(英文)、Threads 3 則(繁中) |
| [reddit.md](reddit.md) | r/software、r/languagelearning 草稿,另附 r/LearnJapanese 版本 |
| [demo-video-script.md](demo-video-script.md) | 45 秒 demo 影片腳本(分鏡、畫面、旁白、字幕) |

## 寫的時候守住的事實(發布前請再核對一次)

- 免費、MIT、Windows / macOS / Android;目前版本 v0.6.2。
- **預設用 Google 翻譯**(文字會送到 Google)。關掉「使用 Google」才是完全離線(Argos,或選用的 TranslateGemma 4B,2.5 GB)。
  所以文案寫「可以完全離線」,不要寫「完全離線的翻譯器」。OCR 一律在本機。
- macOS 版由 CI 建置,作者還沒在真實 Mac 上測過;文案裡如果提 Mac,要附這句。
- 安裝檔沒有程式碼簽章,SmartScreen 會警告。Reddit 一定會有人問,先寫進 FAQ。
- 語音字幕(Whisper / sherpa-onnx)只有 Windows。

## 發布前要準備的

- [ ] 3 張截圖:網頁段落上方的譯文、遊戲對話框(區域模式)、設定視窗。放 `docs/` 並補進 README 預留的位置。
- [ ] 一支 45 秒影片(腳本見 demo-video-script.md),另存 15 秒 GIF 給 X / Reddit。
- [ ] Product Hunt 用的 240×240 圖示(可用 `assets/icon.png` 放大)與 1270×760 圖片。
- [ ] 確認每個 subreddit 的自我推廣規則(r/languagelearning 規定較嚴,可能要在週末的 resource thread 發)。
- [ ] 發文當天能在線回留言至少 3–4 小時。
