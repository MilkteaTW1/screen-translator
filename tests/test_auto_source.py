"""'Auto-detect' for the screen language: read with every installed OCR language, keep each place's reading in its own
script, translate each block from the language it was read in, and leave text already in the target language alone."""
from screen_translator import app as appmod
from screen_translator import ocr
from screen_translator.ocr import AutoRecognizer, Line


class FakeOcr:
    def __init__(self, tag, lines):
        self.tag, self.joiner, self._lines = tag, "" if tag.split("-")[0] in ("ja", "zh") else " ", lines

    def recognize(self, bgra, w, h):
        return [Line(x, y, lw, lh, text, 0, self.tag, self.joiner) for x, y, lw, lh, text in self._lines]


# One screen, read by three engines: each reads its own language properly, and the others see garbage or nothing.
ENGLISH = FakeOcr("en-US", [(10, 10, 400, 20, "The new update includes several improvements."), (10, 60, 380, 20, "xx il Il")])
JAPANESE = FakeOcr("ja", [(10, 60, 380, 20, "このアプリは画面のテキストを翻訳します。"), (10, 10, 400, 20, "ザ ニュー")])
CHINESE = FakeOcr("zh-Hant-TW", [(10, 110, 380, 20, "這個程式可以直接翻譯畫面上的文字。")])


def test_each_place_keeps_the_reading_in_its_own_script():
    lines = AutoRecognizer([ENGLISH, JAPANESE, CHINESE]).recognize(b"", 500, 200)
    assert [(l.tag, l.text[:8]) for l in lines] == [
        ("en-US", "The new "), ("ja", "このアプリは画面"), ("zh-Hant-TW", "這個程式可以直接")]


def test_paragraphs_do_not_join_lines_read_in_different_languages():
    a = Line(10, 10, 300, 20, "This is a sentence that", 0, "en-US", " ")
    b = Line(10, 32, 300, 20, "このアプリは", 0, "ja", "")
    assert len(ocr.merge_paragraphs([a, b])) == 2


def test_the_worker_translates_each_block_from_its_own_language_and_skips_the_target(monkeypatch):
    worker = appmod.Worker(appmod.LANGUAGES)
    worker.settings = {**appmod.DEFAULTS, "source": "auto", "target": "zh-TW"}
    asked = []

    def fake_many(texts, src, dst, tag, glossary, auto, kata):
        asked.append((src, tag, list(texts)))
        return [f"<{src}>" for _ in texts]
    monkeypatch.setattr(worker.translator, "translate_many", fake_many)
    recognizer = AutoRecognizer([ENGLISH, JAPANESE, CHINESE])

    class Shot:
        bgra, width, height = b"", 500, 200
    for _ in range(2):  # a block is shown once seen twice
        items = worker._process(recognizer, Shot, worker.settings)
        worker.dirty = False
    assert ("en", "en-US", ["The new update includes several improvements."]) in asked
    assert ("ja", "ja", ["このアプリは画面のテキストを翻訳します。"]) in asked
    assert not any("這個程式" in t for _src, _tag, texts in asked for t in texts)  # already Chinese: left alone
    assert sorted(i[4] for i in items if i[4]) == ["<en>", "<ja>"]
