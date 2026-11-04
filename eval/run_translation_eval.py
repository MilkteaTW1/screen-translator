"""Measures translation quality: Google and the offline engine on the sentences in translation_set.py, and whether
translating a paragraph whole, by sentence or line by line changes the result.

    python eval/run_translation_eval.py [--save] [--dump outputs.json]

The score is chrF (character n-gram F-score, 0-100) against one reference per sentence, so it says how close the wording
is to that reference, not whether a translation is acceptable: read the outputs (--dump) next to the numbers.
The text goes to Google. Needs the offline pack en>zt for the offline rows."""
import argparse
import json
import statistics
import sys
import textwrap
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from translation_set import PARAGRAPHS, SENTENCES  # noqa: E402

TARGET = "zh-TW"


def _grams(text, n):
    text = "".join(text.split())
    return Counter(text[i:i + n] for i in range(len(text) - n + 1))


def chrf(hyp, ref, max_n=6, beta=2.0):
    """chrF: average over n = 1..6 of the character n-gram precision and recall, then the F-beta of those (recall counts more)."""
    if not hyp:
        return 0.0
    precisions, recalls = [], []
    for n in range(1, max_n + 1):
        h, r = _grams(hyp, n), _grams(ref, n)
        if not h or not r:
            continue
        match = sum((h & r).values())
        precisions.append(match / sum(h.values()))
        recalls.append(match / sum(r.values()))
    if not precisions:
        return 0.0
    p, r = sum(precisions) / len(precisions), sum(recalls) / len(recalls)
    return 0.0 if p + r == 0 else 100 * (1 + beta ** 2) * p * r / (beta ** 2 * p + r)


def make(engine):
    from screen_translator.translator import Translator
    tr = Translator()
    tr.google = engine == "google"
    return tr


def translate(tr, texts):
    out = tr.translate_many(texts, "en", TARGET, "en-US", [], True, False)
    return [o or "" for o in out]


def mean(values):
    return round(statistics.fmean(values), 1) if values else 0.0


def run(engines):
    scores, dump = {}, {}
    for engine in engines:
        tr = make(engine)
        started = time.monotonic()
        per_kind = {}
        failed = 0
        for kind, pairs in SENTENCES.items():
            outs = []
            for i in range(0, len(pairs), 8):  # the way the app sends them: a few lines per request
                outs += translate(tr, [src for src, _ in pairs[i:i + 8]])
            per_kind[kind] = mean([chrf(o, ref) for o, (_, ref) in zip(outs, pairs)])
            failed += sum(1 for o in outs if not o)
            dump.setdefault(engine, {})[kind] = [{"en": src, "ref": ref, "out": o} for o, (src, ref) in zip(outs, pairs)]
        every = [s for s in per_kind.values()]
        scores[engine] = {"sentences": per_kind, "sentences_all": mean(every), "no_answer": failed,
                          "seconds": round(time.monotonic() - started, 1)}
        # Paragraphs: whole / by sentence / line by line (about as a page wraps them)
        modes = {"whole": [], "by_sentence": [], "by_line": []}
        shown = []
        for sentences, ref in PARAGRAPHS:
            whole = " ".join(sentences)
            got = {
                "whole": translate(tr, [whole])[0],
                "by_sentence": "".join(translate(tr, sentences)),
                "by_line": "".join(translate(tr, textwrap.wrap(whole, 38))),
            }
            for mode, hyp in got.items():
                modes[mode].append(chrf(hyp, ref))
            shown.append({"en": whole, "ref": ref, **got})
        scores[engine]["paragraphs"] = {mode: mean(v) for mode, v in modes.items()}
        dump[engine]["paragraphs"] = shown
    return scores, dump


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--save", action="store_true", help="write translation_baseline.json")
    ap.add_argument("--dump", help="write every output next to its reference to this file")
    ap.add_argument("--engines", default="google,offline")
    args = ap.parse_args()
    scores, dump = run(args.engines.split(","))
    print(json.dumps(scores, indent=2, ensure_ascii=False))
    if args.dump:
        Path(args.dump).write_text(json.dumps(dump, indent=1, ensure_ascii=False), encoding="utf-8")
    if args.save:
        (Path(__file__).parent / "translation_baseline.json").write_text(
            json.dumps(scores, indent=2, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
