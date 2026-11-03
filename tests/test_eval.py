"""Keeps reading and box handling from getting worse than eval/baseline.json. See eval/README.md."""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1] / "eval"
sys.path.insert(0, str(ROOT))
import run_eval  # noqa: E402

BASE = json.loads((ROOT / "baseline.json").read_text(encoding="utf-8"))


def test_every_answer_box_lies_inside_its_picture():
    for e in run_eval.index().values():
        h, w = run_eval.picture(e["name"]).shape[:2]
        assert e["lines"], e["name"]
        assert all(0 <= l["x"] and l["x"] + l["w"] <= w + 1 and 0 <= l["y"] for l in e["lines"]), e["name"]
        assert h >= 720


def test_scroll_measurement_is_never_wrong_and_rarely_refuses():
    tall = [e for e in run_eval.index().values() if e["kind"] == "tall"]
    got = run_eval.eval_follow(tall)
    for step, row in got.items():
        assert row["wrong"] == 0, step
        assert row["good"] >= BASE["follow"][step]["good"], step


def test_reading_is_no_worse_than_the_baseline():
    stills = [e for e in run_eval.index().values() if e["kind"] == "still" and e["lang"] == "en-US"]
    try:
        reader = run_eval.windows_reader(lambda e: "en-US")
        reader(run_eval.picture(stills[0]["name"]), stills[0])
    except RuntimeError:
        pytest.skip("no English OCR installed in Windows")
    got = run_eval.eval_ocr(stills, reader)["all"]
    base = BASE["ocr_chosen"]["by"]["lang:en"]
    assert got["cer"] <= base["cer"] + 0.002
    assert got["missed"] <= base["missed"]
    assert got["noise"] <= base["noise"]


def test_boxes_follow_a_scroll_and_old_text_leaves_no_box():
    ix = run_eval.index()
    try:
        run_eval.ocr.make_recognizer("en-US")
    except RuntimeError:
        pytest.skip("no English OCR installed in Windows")
    got = run_eval.eval_boxes(ix, True)
    for name, r in got.items():
        base = BASE["boxes_hidden"][name]
        assert r["after_7s"]["stale"] <= base["after_7s"]["stale"], name
        assert r["after_7s"]["misplaced"] <= base["after_7s"]["misplaced"], name
        assert r["after_7s"]["overlaps"] <= base["after_7s"]["overlaps"], name
        if base["err_moving_px"] is not None:
            assert r["err_moving_px"] <= base["err_moving_px"] + 2, name


@pytest.mark.parametrize("hide", [True, False])
def test_boxes_do_not_flicker_while_something_else_on_screen_moves(hide):
    try:
        run_eval.ocr.make_recognizer("en-US")
    except RuntimeError:
        pytest.skip("no English OCR installed in Windows")
    got = run_eval.eval_flicker(run_eval.index(), hide, names=("cards-dark-12",), seconds=8)
    assert got["cards-dark-12"] == 0


def test_a_box_hiding_text_that_vanished_goes_away_even_when_boxes_are_in_the_picture():
    ix = run_eval.index()
    try:
        run_eval.ocr.make_recognizer("en-US")
    except RuntimeError:
        pytest.skip("no English OCR installed in Windows")
    for name, r in run_eval.eval_boxes(ix, False).items():
        if name.startswith("vanish"):
            assert r["after_7s"]["stale"] == 0, name
