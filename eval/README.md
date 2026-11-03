# Evaluation set

Pictures of made-up pages, with the right answers taken from the pages themselves, so a change to reading or to the
translation boxes can be measured instead of judged from one screenshot.

- `make_fixtures.py` draws the pictures with headless Chrome. They are committed, so only changing the set needs a browser.
- `run_eval.py` prints the scores. `--save` writes `baseline.json`; `--rapid` also tries RapidOCR, if it is installed.
- `tests/test_eval.py` fails when a score gets worse than the baseline. When a change really improves things, save a new baseline with it.

**What is measured**

- Reading: wrong characters, lines missed, things read that are not text, time per picture.
- Scroll: how often the measured shift is right.
- Boxes: the real Worker and Overlay on a scroll and on text that vanishes: boxes for text no longer on screen (`stale`), boxes
  far from their text (`misplaced`), boxes on top of each other (`overlaps`), distance from the text while moving (`err_moving_px`).

**What it does not show**

The pages are clean browser renderings in a few layouts, not real websites, so real pages may read worse. Video and photos are
not covered. The box runs use a stand-in translator and clock, so OCR and network delays are left out, and translation quality
is not measured at all. The Android app is not covered. CI machines have no OCR language packs, so there only the scroll test
and the checks of the set itself run; run the rest on a Windows machine that has them.
