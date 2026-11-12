# Product Hunt 上架草稿

## Name

Screen Translator

## Tagline(上限 60 字元)

主推:

> Translations drawn right above the text on your screen

備選:

- `Translate any app or game in place, online or fully offline` (59)
- `Free screen OCR translator that can run with no internet` (56)

## Topics

Productivity, Languages, Open Source, Windows

## Description(上限 260 字元)

> Screen Translator reads the text on your screen and draws the translation above each block, in any app or game.
> OCR runs on your PC. Translation uses Google by default, or stays fully offline with Argos or TranslateGemma.
> Free and MIT, for Windows, Mac and Android.

(約 255 字元,貼上前再數一次)

## First comment (maker comment)

> Hi Product Hunt,
>
> I built this because I kept copying text out of games and English-only tools into a translator tab, then
> switching back. I wanted the translation to sit where the text is.
>
> How it works: every second or so it reads the screen with the OCR that is already in Windows (Apple Vision on a Mac,
> ML Kit on Android), joins wrapped lines back into sentences, translates them, and paints each translation just above its
> paragraph in a click-through overlay. The overlay is hidden from screen capture, so it never ends up translating itself.
>
> A few things that took most of the work:
>
> - Names stay as they are. Capitalised words mid-sentence, CamelCase and ALL CAPS are kept out of the translation, and you
>   can add your own glossary ("thread = 執行緒").
> - Scrolling: it measures how far the page moved and carries the translations with it instead of re-reading everything.
> - Region / game mode (Ctrl+Alt+R): drag a box over subtitles or a dialogue window and only that area is scanned, faster.
> - Speech captions (Windows): what your PC plays is transcribed locally with Whisper and translated in a strip at the bottom.
>
> On privacy, to be precise: the screen is always read locally. Translation goes to Google by default because it is the
> best free option. Turn that off and it switches to Argos Translate on your machine, with an optional 2.5 GB TranslateGemma
> model for better wording. You can also plug in your own DeepL or Gemini key, or a local Ollama / LM Studio server.
> No account, no telemetry.
>
> Honest limits: the small offline models are clearly worse than Google on long sentences, the Windows installer is not
> code-signed yet (SmartScreen will warn), and I have not tested the Mac build on a real Mac. If you try it there, I would
> really like to hear how it goes.
>
> It is free and open source (MIT). Feedback on which apps or games it struggles with is the most useful thing you can send me.

## Gallery 圖片順序(1270×760)

1. 一個英文網頁,每段上方都有繁中譯文(主視覺,一眼看懂在做什麼)
2. 遊戲對話框 + 區域模式的框線
3. 「Translate / Speech / Quality / General」設定視窗,Use Google 開關清楚可見
4. 隱私表格(取自 README,做成圖)
5. 語音字幕條(影片或直播畫面下方)

## 上架時間

太平洋時間週二至週四 00:01 上架。台灣時間是當天下午 3–4 點,首 4 小時需要有人在線回覆。
