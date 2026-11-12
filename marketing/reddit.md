# Reddit 草稿

發文前先讀各版規則。多數版要求作者表明身分、不能只丟連結,而且自己的帖子要跟一般討論保持合理比例。
標題不要用全大寫或 emoji。留言區有人問問題就回,不要回「Thanks!」就結束。

---

## r/software

**Title:** I made a free screen translator that draws translations above the original text (Windows/Mac/Android, can run offline)

**Body:**

> I'm the developer. Screen Translator reads the text on your screen and draws the translation in a click-through
> overlay right above each paragraph, so you don't have to copy anything into a translator.
>
> **How it works**
> - OCR: Windows' built-in OCR (Apple Vision on Mac, ML Kit on Android), so reading the screen never leaves your PC.
> - Translation: Google by default. Turn it off and it uses Argos Translate locally; there's an optional 2.5 GB
>   TranslateGemma model for better offline wording. You can also use your own DeepL/Gemini key or an Ollama / LM Studio server.
> - Wrapped lines are joined into sentences before translating, and names (mid-sentence capitals, CamelCase) are left alone.
> - When you scroll, it tracks how far the page moved and carries the translations along instead of re-reading.
>
> **Other bits:** region mode for subtitles and game dialogue (Ctrl+Alt+R), hover mode, a glossary, speech captions
> from your PC's audio via local Whisper (Windows).
>
> **Known limits:** offline translation quality is noticeably below Google on long sentences. The installer isn't
> code-signed, so SmartScreen warns on first run. The Mac build comes from CI and I haven't run it on a real Mac yet.
>
> Free, MIT licensed, ~70 MB installer: https://github.com/MilkteaTW1/screen-translator
>
> I'd like to know which apps or games it does badly on. Screenshots of failures help the most.

**預想問答(先備好):**

- *Why not just use Google Lens / PowerToys Text Extractor?* Those translate a snapshot you take. This one keeps running and
  updates in place while you read or play.
- *Is it safe? SmartScreen warns.* It's unsigned because a code-signing certificate costs money; the source and the CI build
  that made the installer are both public.
- *Linux?* Not yet. OCR is the missing piece (would need Tesseract or similar).

---

## r/languagelearning

這個版對工具推廣比較嚴,通常要放在每週的資源討論串,或者把重點放在「怎麼用來學語言」而不是介紹產品。以下是學習導向的版本。

**Title:** I use an on-screen translator while reading in my target language. Here's the setup, and a free tool I made for it

**Body:**

> When I read in a language I'm still learning, I want the original in front of me and a translation nearby
> to check myself, without switching tabs. So I built a small tool that does exactly that: it reads the screen and puts
> the translation just above each paragraph, leaving the original visible.
>
> How I use it for learning:
> - **Hover mode**: translations stay hidden until I move the mouse over a paragraph. I read first, then check.
> - **Glossary**: words I want to keep in the original language (or force a translation for) go in a list.
> - **Region mode**: for a show or a game, I drag a box over the subtitles and only those are translated.
> - **Speech captions** (Windows): it transcribes what's playing and shows the original sentence plus translation at the bottom.
>
> It works with any language your OS can read (on Windows you may need to add the OCR language in Settings).
> Reading the screen happens on your computer. Translation uses Google by default, or can run fully offline.
>
> It's free and open source: https://github.com/MilkteaTW1/screen-translator
>
> Curious whether others use something similar, and whether always-visible translations help or get in the way of learning.

---

## r/LearnJapanese(選用)

**Title:** Free tool that translates Japanese on screen while keeping the original visible (games, VNs, websites)

**Body 重點(依版規調整):**

> - Windows needs the Japanese OCR pack installed (Settings > Time & language > Language & region > Japanese > Optional features).
> - Katakana words can be kept untranslated (a setting), which helps with names and loanwords.
> - Region mode for a VN's text box. Hover mode to only peek when stuck.
> - Honest limit: vertical text is not handled well, and the offline ja→en model is weak; Google mode is much better.

(發文前請自己再實測直書與 VN 的狀況,確認上面的限制寫得準確。)
