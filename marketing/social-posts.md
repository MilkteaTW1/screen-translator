# 社群貼文草稿

每則都附一段 GIF 或影片。純文字連結在 X 和 Threads 的觸及都很差,連結建議放在第一則回覆裡。

---

## Twitter / X(英文)

### 1. 介紹

> I got tired of copying text from games into a translator tab, so I made a tool that draws the translation right above the text on screen.
>
> Reads the screen with Windows' own OCR. Uses Google, or fully offline with Argos / TranslateGemma.
>
> Free, MIT, Windows + Mac + Android.
>
> [GIF: English web page → translations appear above each paragraph]

回覆內第一則:`github.com/MilkteaTW1/screen-translator`

### 2. 遊戲 / 區域模式

> Ctrl+Alt+R, drag a box over a game's dialogue window, and only that area gets translated. It scans faster and drops old lines sooner when the text changes.
>
> Works on anything you can see, no game hooks or memory reading.
>
> [GIF: region drag → dialogue box translated, next line appears]

### 3. 隱私 / 離線

> What leaves your PC when you use Screen Translator:
>
> OCR: nothing, it's Windows' built-in engine
> Translation: the text goes to Google by default; switch it off and Argos translates locally
> Speech captions: nothing, Whisper runs on your CPU
>
> No account. No telemetry. Source is on GitHub.

---

## Threads(繁體中文)

### 1. 介紹

> 玩外文遊戲、看英文文件時,一直複製貼上到翻譯網頁很煩,所以做了一個小工具:
> 譯文直接畫在螢幕上原文的正上方,滑鼠照樣可以點穿,不影響操作。
>
> 用 Windows 內建的 OCR 讀畫面,預設用 Google 翻譯,也可以一鍵改成完全離線。
> 免費、開源,Windows / Mac / Android 都有。
>
> [影片:英文網頁 → 每段上方出現中文]

### 2. 給玩遊戲 / 看字幕的人

> 按 Ctrl+Alt+R 框住遊戲對話框或影片字幕,就只翻那一塊,掃得比較快,換下一句時舊的譯文也會比較快消失。
> 不用改遊戲檔、不讀記憶體,畫面上看得到的字都能翻。
>
> 人名、角色名不會被亂翻:句中大寫開頭的字會保留原文,也可以自己加「不翻譯清單」或指定譯名(例如 thread = 執行緒)。

### 3. 離線與隱私

> 很多人問「會不會把螢幕傳出去」,直接說清楚:
>
> ・讀取螢幕文字:一律在你的電腦上(Windows 內建 OCR)
> ・翻譯:預設送 Google;關掉「使用 Google」就改用本機的 Argos,完全不連網
> ・想要更好的離線譯文:可選下載 TranslateGemma 4B(2.5 GB)
> ・語音字幕:Whisper 在本機跑
>
> 不用註冊,沒有追蹤。原始碼在 GitHub,連結放留言。
