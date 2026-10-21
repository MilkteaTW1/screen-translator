# Architecture

```
src/screen_translator/
  app.py         Worker thread (scan loop, block tracking, batching), settings panel, tray icon
  ocr.py         Windows OCR wrapper; merge_paragraphs joins wrapped lines into sentences
  translator.py  Offline translation (packs.py runs Argos packs on CTranslate2), source-language filters, proper-noun protection
  overlay.py     Transparent click-through overlay; one translation box above each block
scripts/download_packs.py   Install Argos language packs
tests/                      pytest suite (filters, paragraph merge, overlay placement)
```

## Pipeline (one scan)

1. `mss` grabs the primary monitor (or the `region`); a cheap frame diff decides whether to rescan.
2. `ocr.Recognizer` returns lines; `looks_like_source` drops everything not in the source language
   (URLs, handles, ids, menu bars, single words, icon noise).
3. `merge_paragraphs` joins stacked lines until a sentence-ending punctuation mark.
4. Blocks are matched to *tracks* from earlier scans (IoU > 0.5 and text similarity >= 0.8). Tracks keep
   their translation and position; new ones appear after being seen twice; shown ones survive one missed
   scan on a static screen.
5. `Translator.translate` swaps proper nouns for `Z{n}Z` placeholders, translates with Argos, restores them,
   and rejects bad output (identical text, repetition loops, wrong script).
6. `Overlay` draws each translation centred above its block. Position depends only on the block.

## Tuning knobs

`MAX_BLOCKS`, `BATCH` in `app.py`; thresholds in `ocr.merge_paragraphs`, `translator.looks_like_source`,
`Worker._same_place`.
