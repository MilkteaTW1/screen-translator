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


def test_background_translation_does_not_block_scanning(monkeypatch):
    """Translation waits on the network; the scan must come back at once and the result arrive later."""
    import threading
    import time
    from screen_translator import app as appmod
    release = threading.Event()
    worker = appmod.Worker(appmod.LANGUAGES)
    worker.settings = {**appmod.DEFAULTS}
    worker.running, worker.background_translation = True, True

    def slow(texts, *a):
        release.wait(5)
        return ["譯:" + t for t in texts]
    monkeypatch.setattr(worker.translator, "translate_many", slow)
    threading.Thread(target=worker._translate_loop, daemon=True).start()
    track = {"x": 0, "y": 0, "w": 10, "h": 10, "lh": 10, "text": "Hello there", "tag": "en-US", "translation": None,
             "done": False, "seen": 2, "missed": 0}
    worker.tracks = [track]
    start = time.monotonic()
    worker._jobs.append([track])
    track["queued"] = True
    worker._jobs_ready.set()
    assert time.monotonic() - start < 0.5 and not track["done"]  # not waiting for the translation
    release.set()
    for _ in range(50):
        if track["done"]:
            break
        time.sleep(0.1)
    worker.running = False
    worker._jobs_ready.set()
    assert track["translation"] == "譯:Hello there" and not track["queued"]


def test_translations_stay_on_screen_and_lead_while_scrolling():
    """While the page scrolls, translations keep showing, drawn a little ahead along the scroll (each picture is
    already late when drawn); once it stops they sit exactly on their text again."""
    import time
    from screen_translator import app as appmod
    worker = appmod.Worker(appmod.LANGUAGES)
    worker.tracks = [{"x": 0, "y": 500, "w": 10, "h": 10, "lh": 10, "text": "Hi there", "tag": "en-US",
                      "translation": "嗨", "done": True, "seen": 2, "missed": 0}]
    now = time.monotonic()
    worker.scrolling_until, worker.velocity = now + 0.3, (0.0, -500.0)  # scrolling down: text moves up
    worker._last_follow = now  # the picture the tracks come from was taken just now
    moving = worker._snapshot(now)[0]
    # ahead by the display delay plus the (tiny) time since that picture
    assert moving[4] == "嗨" and 500 - round(500 * (appmod.SCROLL_LEAD + 0.05)) <= moving[1] <= 500 - round(500 * appmod.SCROLL_LEAD)
    assert worker._snapshot(now + 0.5)[0][1] == 500
