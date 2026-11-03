"""Scores reading and box handling against the pictures in eval/fixtures, whose right answers come from the pages.

    python eval/run_eval.py                 everything this machine can run, printed as tables
    python eval/run_eval.py --rapid         also RapidOCR, if it is installed (not a dependency of the app)
    python eval/run_eval.py --save          also write eval/baseline.json, which tests/test_eval.py compares against

Sections: OCR (error rate, missed lines, noise, time), follow (scroll shift measured without any OCR) and boxes (the
real Worker and Overlay on scroll and vanishing-text sequences, with a stand-in translator and a stand-in clock, so
OCR time and network time are not part of it).
"""
import argparse
import difflib
import json
import os
import statistics
import sys
import time
import types
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import PySide6.QtWidgets  # noqa: F401,E402  Qt before winrt, or the process crashes
import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent / "src"))
from screen_translator import app as appmod, ocr, overlay as overlaymod, tracking  # noqa: E402
from screen_translator.overlay import Overlay  # noqa: E402
from PySide6.QtGui import QImage  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

FIX = ROOT / "fixtures"
HEIGHT = 720


def index():
    return {e["name"]: e for e in json.loads((FIX / "index.json").read_text(encoding="utf-8"))}


def picture(name):
    return np.asarray(Image.open(FIX / f"{name}.png").convert("RGBA"))[:, :, [2, 1, 0, 3]].copy()  # BGRA


def visible(lines, top=0, height=HEIGHT):
    """The answer lines fully inside a window of the page, in window coordinates."""
    return [{**l, "y": l["y"] - top} for l in lines if l["y"] >= top and l["y"] + l["h"] <= top + height]


def squeeze(text):
    return "".join(text.split())


def edits(a, b):
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def _touch(g, o):
    """(x, y, w, h, ...) answer line g and read line o are on the same text: same row, overlapping sideways."""
    iy = min(g["y"] + g["h"], o["y"] + o["h"]) - max(g["y"], o["y"])
    ix = min(g["x"] + g["w"], o["x"] + o["w"]) - max(g["x"], o["x"])
    return ix > 0 and iy >= 0.5 * min(g["h"], o["h"])


def reading_order(lines):
    """Top to bottom, and left to right within a row (a box a few pixels higher is still in the same row)."""
    rows = []
    for l in sorted(lines, key=lambda l: l["y"]):
        if rows and l["y"] < rows[-1][0]["y"] + 0.6 * rows[-1][0]["h"]:
            rows[-1].append(l)
        else:
            rows.append([l])
    return [l for row in rows for l in sorted(row, key=lambda l: l["x"])]


def score_reading(answers, read, clipped=()):
    """Groups answer lines with the read lines that touch them, then compares each group as one string.
    `read` is a list of dicts with x, y, w, h, text. `clipped` are answer lines cut off by the picture's edge: reading
    them is neither right nor wrong, so they are left out of both the score and the noise."""
    read = [o for o in read if not any(_touch(g, o) for g in clipped)]
    groups, seen_a, seen_r = [], set(), set()
    for start in range(len(answers)):
        if start in seen_a:
            continue
        a_ids, r_ids, todo = {start}, set(), [("a", start)]
        while todo:
            kind, i = todo.pop()
            if kind == "a":
                for j, o in enumerate(read):
                    if j not in r_ids and _touch(answers[i], o):
                        r_ids.add(j)
                        todo.append(("r", j))
            else:
                for j, g in enumerate(answers):
                    if j not in a_ids and _touch(g, read[i]):
                        a_ids.add(j)
                        todo.append(("a", j))
        seen_a |= a_ids
        seen_r |= r_ids
        groups.append((a_ids, r_ids))
    chars = errors = missed = exact = 0
    for a_ids, r_ids in groups:
        ref = squeeze("".join(l["text"] for l in reading_order([answers[i] for i in a_ids])))
        hyp = squeeze("".join(l["text"] for l in reading_order([read[j] for j in r_ids])))
        chars += len(ref)
        errors += edits(ref, hyp)
        exact += ref == hyp
        missed += len(a_ids) if not r_ids else 0
    return {"chars": chars, "errors": errors, "groups": len(groups), "exact": exact, "missed": missed,
            "lines": len(answers), "noise": len(read) - len(seen_r), "noise_text": [read[j]["text"] for j in range(len(read)) if j not in seen_r]}


def as_dicts(lines):
    return [{"x": l.x, "y": l.y, "w": l.w, "h": l.h, "text": l.text} for l in lines]


def summarize(rows):
    chars = sum(r["chars"] for r in rows)
    return {"cer": round(sum(r["errors"] for r in rows) / max(1, chars), 4), "missed": sum(r["missed"] for r in rows),
            "lines": sum(r["lines"] for r in rows), "noise": sum(r["noise"] for r in rows),
            "exact": round(sum(r["exact"] for r in rows) / max(1, sum(r["groups"] for r in rows)), 3),
            "ms": round(statistics.median(r["ms"] for r in rows))}


def eval_ocr(entries, read_fn):
    """Reads each still picture. Returns (summary overall, by theme, worst pictures, noise samples)."""
    rows = []
    for e in entries:
        a = picture(e["name"])
        answers = visible(e["lines"])
        clipped = [l for l in e["lines"] if l["y"] < HEIGHT and l["y"] + l["h"] > HEIGHT]
        t = time.perf_counter()
        read = read_fn(a, e)
        ms = (time.perf_counter() - t) * 1000
        rows.append({**score_reading(answers, read, clipped), "ms": ms, "name": e["name"]})
    themes = {}
    for r in rows:
        parts = r["name"].split("-")
        themes.setdefault(parts[1] if len(parts) > 1 else parts[0], []).append(r)
        themes.setdefault("lang:" + parts[0] if parts[0] in ("zh", "ja") else "lang:en", []).append(r)
    worst = sorted(rows, key=lambda r: -r["errors"] / max(1, r["chars"]))[:5]
    return {"all": summarize(rows), "by": {k: summarize(v) for k, v in sorted(themes.items())},
            "worst": [(r["name"], round(r["errors"] / max(1, r["chars"]), 3)) for r in worst],
            "noise_text": sorted({t for r in rows for t in r["noise_text"]})[:15]}


def windows_reader(lang_of):
    made = {}

    def read(a, e):
        tag = lang_of(e)
        rec = made.setdefault(tag, ocr.make_recognizer(tag))
        return as_dicts(rec.recognize(a.tobytes(), a.shape[1], a.shape[0]))
    return read


def rapid_readers():
    from rapidocr_onnxruntime import RapidOCR
    engine = RapidOCR()
    made = {}

    def full(a, e):
        res, _ = engine(np.ascontiguousarray(a[:, :, :3]))
        out = []
        for box, text, _conf in res or []:
            b = np.array(box)
            x0, y0, x1, y1 = b[:, 0].min(), b[:, 1].min(), b[:, 0].max(), b[:, 1].max()
            out.append({"x": float(x0), "y": float(y0), "w": float(x1 - x0), "h": float(y1 - y0), "text": text})
        return out

    def hybrid(a, e):
        """Windows finds the lines, RapidOCR reads each one again."""
        rec = made.setdefault(e["lang"], ocr.make_recognizer(e["lang"]))
        out = []
        for l in as_dicts(rec.recognize(a.tobytes(), a.shape[1], a.shape[0])):
            y0, y1, x0, x1 = max(0, int(l["y"]) - 3), int(l["y"] + l["h"]) + 3, max(0, int(l["x"]) - 3), int(l["x"] + l["w"]) + 3
            crop = np.ascontiguousarray(a[y0:y1, x0:x1, :3])
            res, _ = engine(crop, use_det=False, use_cls=False)
            if res and res[0][1] >= 0.5:  # below this it is more likely a picture than text
                l["text"] = res[0][0]
                out.append(l)
        return out
    return full, hybrid


def eval_follow(entries):
    """How often the measured scroll is right, for several step sizes, with no OCR involved."""
    out = {}
    for e in entries:
        page = picture(e["name"])[:, :, 1]
        for step in (8, 45, 120, 300):
            good = bad = none = 0
            for top in range(0, page.shape[0] - HEIGHT - step, 150):
                tracks = [{**l} for l in visible(e["lines"], top)]
                got = tracking.follow(tracks, page[top:top + HEIGHT], page[top + step:top + step + HEIGHT])
                if got is None:
                    none += 1
                elif got == (0, -step):
                    good += 1
                else:
                    bad += 1
            row = out.setdefault(str(step), {"good": 0, "wrong": 0, "refused": 0})
            row["good"] += good
            row["wrong"] += bad
            row["refused"] += none
    return out


class Clock:
    def __init__(self):
        self.now = 1000.0

    def monotonic(self):
        return self.now

    def sleep(self, s):
        self.now += s


def composite(base, ov):
    img = ov.grab().toImage().convertToFormat(QImage.Format_ARGB32)
    top = np.frombuffer(img.constBits(), np.uint8).reshape(img.height(), img.width(), 4).astype(np.float32)
    alpha = top[:, :, 3:4] / 255.0
    out = base.astype(np.float32)
    out[:, :, :3] = top[:, :, :3] * alpha + out[:, :, :3] * (1 - alpha)
    return out.astype(np.uint8)


class Shot:
    def __init__(self, a):
        self.bgra, self.width, self.height = a.tobytes(), a.shape[1], a.shape[0]


def _share(gt_text, block):
    """How much of an answer line is inside a translated block (0..1)."""
    a, b = squeeze(gt_text).lower(), squeeze(block).lower()
    if not a or not b:
        return 0.0
    matched = difflib.SequenceMatcher(None, a, b, autojunk=False).get_matching_blocks()  # a dropped "·" is still the same line
    return sum(m.size for m in matched if m.size >= 3) / len(a)


def look(ov, source_of, answers):
    """What is drawn compared with what is on screen right now."""
    stale = misplaced = 0
    errors = []
    covered = set()
    for x, y, _w, _h, text, lh in ov.items:
        if not text or text not in ov.drawn:
            continue
        block = source_of.get(text, "")
        hits = [(i, g) for i, g in enumerate(answers) if _share(g["text"], block) >= 0.6 and len(squeeze(g["text"])) >= 3]
        if not hits:
            stale += 1
            continue
        covered |= {i for i, _g in hits}
        err = min(abs(y - g["y"]) for _i, g in hits)
        errors.append(err)
        misplaced += err > max(lh or 0, 20)
    rects = list(ov.drawn.values())
    overlaps = 0
    for i, a in enumerate(rects):
        for b in rects[i + 1:]:
            r = a.intersected(b)
            smaller = min(a.width() * a.height(), b.width() * b.height())
            overlaps += smaller > 0 and r.width() * r.height() / smaller > 0.3
    return {"sources": frozenset(source_of.get(t, "") for t in ov.drawn), "drawn": len(ov.drawn), "stale": stale, "misplaced": misplaced, "overlaps": overlaps,
            "err": errors, "covered": len(covered), "lines": len(answers)}


def simulate(frames, lang, hide):
    """Runs the real Worker and Overlay over `frames`: (picture, answers). Yields what `look` saw after each frame."""
    qapp = QApplication.instance() or QApplication([])
    clock = Clock()
    saved = appmod.time, overlaymod.time
    appmod.time = overlaymod.time = types.SimpleNamespace(monotonic=clock.monotonic, sleep=clock.sleep, time=clock.monotonic, perf_counter=clock.monotonic)
    try:
        h, w = frames[0][0].shape[:2]
        ov = Overlay(qapp.primaryScreen())
        ov.scale = 1.0
        ov.setGeometry(0, 0, w, h)
        worker = appmod.Worker(appmod.LANGUAGES)
        worker.settings = {**appmod.DEFAULTS, "hide_from_capture": hide, "interval": 0.0, "source": lang}
        worker.overlay_rects = ov.painted_rects
        worker._recognizer = ocr.make_recognizer(lang)
        worker.results.connect(ov.set_items)
        worker.background.connect(lambda b: ov.set_background(*b))
        worker.motion.connect(ov.set_motion)
        source_of = {}

        def translate_many(texts, *_a):
            out = []
            for t in texts:
                mark = f"譯{len(source_of)}" + ("這是一段翻譯內容" * 30)[:max(4, len(t) // 2)]
                source_of[mark] = t
                out.append(mark)
            return out
        worker.translator.translate_many = translate_many
        seen = []
        for base, answers in frames:
            clock.now += appmod.POLL + 0.03  # about one look at the screen
            worker._step(Shot(base if hide else composite(base, ov)), clock.monotonic())
            ov.grab()
            seen.append(look(ov, source_of, answers))
        return seen
    finally:
        appmod.time, overlaymod.time = saved


STEP = 0.11  # seconds per simulated frame


def boxes_case(frames, marks, lang, hide):
    """Sums up one sequence. `marks` is {label: frame index} of the moments to report."""
    seen = simulate(frames, lang, hide)
    moving = [e for s in seen[marks["scroll_from"]:marks["scroll_to"]] for e in s["err"]] if "scroll_from" in marks else []
    out = {}
    for label, i in marks.items():
        if label.startswith("scroll"):
            continue
        s = seen[i]
        out[label] = {k: s[k] for k in ("drawn", "stale", "misplaced", "overlaps", "covered", "lines")}
    out["err_moving_px"] = round(statistics.mean(moving), 1) if moving else None
    return out


def eval_flicker(ix, hide, names=("forum-dark-16", "article-light-16", "cards-dark-12"), seconds=15):
    """Translations that come and go on a page that stays put, while something elsewhere on the screen keeps moving."""
    out = {}
    for name in names:
        e, base, answers = ix[name], picture(name), visible(ix[name]["lines"])
        frames = []
        for i in range(int(seconds / STEP)):
            a = base.copy()
            x = 900 + int(150 * np.sin(i / 3))
            a[560:700, x:x + 200, :3] = (40 + i * 7 % 200, 90, 200)  # like a video playing in a corner
            frames.append((a, answers))
        seen = simulate(frames, e["lang"], hide)[int(2 / STEP):]
        out[name] = sum(len(a["sources"] ^ b["sources"]) for a, b in zip(seen, seen[1:]))
    return out


def eval_boxes(ix, hide):
    res = {}
    settle = int(1 / STEP)
    long_settle = int(7 / STEP)
    for name in ("scroll-forum-dark", "scroll-article-light"):
        e = ix[name]
        page = picture(name)
        frames = []
        for _ in range(settle * 2):
            frames.append((page[:HEIGHT], visible(e["lines"])))
        top, moves = 0, 22
        start = len(frames)
        for _ in range(moves):
            top += 45
            frames.append((page[top:top + HEIGHT], visible(e["lines"], top)))
        stop = len(frames)
        for _ in range(long_settle):
            frames.append((page[top:top + HEIGHT], visible(e["lines"], top)))
        res[name] = boxes_case(frames, {"scroll_from": start, "scroll_to": stop, "after_1s": stop + settle - 1, "after_7s": len(frames) - 1}, e["lang"], hide)
    for k in (0, 1):
        a, b = ix[f"vanish{k}-a"], ix[f"vanish{k}-b"]
        frames = [(picture(a["name"]), visible(a["lines"]))] * (settle * 2)
        stop = len(frames)
        frames = frames + [(picture(b["name"]), visible(b["lines"]))] * long_settle
        res[f"vanish{k}"] = boxes_case(frames, {"before": stop - 1, "after_1s": stop + settle - 1, "after_7s": len(frames) - 1}, a["lang"], hide)
    return res


def print_ocr(title, r):
    a = r["all"]
    print(f"\n{title}: error rate {a['cer'] * 100:.2f}%  exact groups {a['exact'] * 100:.0f}%  missed {a['missed']}/{a['lines']} lines  noise {a['noise']}  {a['ms']} ms per picture")
    for k, v in r["by"].items():
        print(f"  {k:<14} error {v['cer'] * 100:6.2f}%  missed {v['missed']:>3}/{v['lines']:<4} noise {v['noise']:>3}")
    print("  worst:", r["worst"])
    print("  noise read:", r["noise_text"])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rapid", action="store_true")
    ap.add_argument("--save", action="store_true")
    args = ap.parse_args()
    ix = index()
    stills = [e for e in ix.values() if e["kind"] == "still"]
    results = {}
    results["ocr_chosen"] = eval_ocr(stills, windows_reader(lambda e: e["lang"]))
    print_ocr("Windows OCR, language chosen", results["ocr_chosen"])
    results["ocr_auto"] = eval_ocr(stills, windows_reader(lambda e: "auto"))
    print_ocr("Windows OCR, automatic language", results["ocr_auto"])
    results["follow"] = eval_follow([e for e in ix.values() if e["kind"] == "tall"])
    print("\nScroll measured (no OCR):", results["follow"])
    for hide in (True, False):
        key = "boxes_hidden" if hide else "boxes_in_picture"
        results[key] = eval_boxes(ix, hide)
        print(f"\nBoxes, hide_from_capture={hide}:")
        for name, r in results[key].items():
            print(f"  {name}: {r}")
        results["flicker_" + key] = eval_flicker(ix, hide)
        print("  flicker in 15 s:", results["flicker_" + key])
    if args.rapid:
        full, hybrid = rapid_readers()
        en = [e for e in stills if e["lang"] == "en-US"]
        results["rapid_full"] = eval_ocr(stills, full)
        print_ocr("RapidOCR, whole picture", results["rapid_full"])
        results["rapid_hybrid"] = eval_ocr(en, hybrid)
        print_ocr("Windows finds, RapidOCR reads (English pictures)", results["rapid_hybrid"])
    if args.save:
        keep = {k: results[k] for k in ("ocr_chosen", "follow", "boxes_hidden", "boxes_in_picture", "flicker_boxes_hidden", "flicker_boxes_in_picture")}
        (ROOT / "baseline.json").write_text(json.dumps(keep, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
