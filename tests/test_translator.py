from screen_translator.translator import looks_like_source, protect, restore


def test_english_sentence_is_source():
    assert looks_like_source("This is a normal sentence about cats.", "en-US")


def test_urls_handles_and_single_words_are_not_source():
    for text in ("https://example.com/page", "@someone_else", "Premium", "a1b2c3d4e5"):
        assert not looks_like_source(text, "en-US"), text


def test_chinese_page_is_not_japanese():
    assert not looks_like_source("這是一段中文內容", "ja-JP")


def test_proper_nouns_round_trip():
    text = "I met Hatsune Miku at the NVIDIA event"
    protected, originals = protect(text, ["Hatsune Miku"], "en", True, False)
    assert "Hatsune" not in protected
    assert restore(protected, originals) == text


def test_needed_pairs_pivot_through_english():
    from screen_translator.translator import needed_pairs
    assert needed_pairs("en", "zh-TW") == [("en", "zt")]
    assert needed_pairs("ja", "zh-TW") == [("ja", "en"), ("en", "zt")]
    assert needed_pairs("en", "en") == []


def test_llm_engine_is_used_and_falls_back(monkeypatch):
    from screen_translator import translator as t
    tr = t.Translator()
    tr.llm = ("http://x/v1", "m")
    monkeypatch.setattr(t, "llm_translate", lambda text, *a: "你好，世界。")
    assert tr.translate("Hello there, world.", "en", "zh-TW", "en-US", [], True, False) == "你好，世界。"
    assert tr.engine == "llm"
    tr.clear()

    def down(*a):
        raise OSError("refused")
    monkeypatch.setattr(t, "llm_translate", down)
    monkeypatch.setattr(tr, "_argos_many", lambda texts, *a: ["離線翻譯。"] * len(texts))
    assert tr.translate("Hello there, world.", "en", "zh-TW", "en-US", [], True, False) == "離線翻譯。"
    assert tr.engine == "offline"


class _FakeEngine:
    """Stands in for the CTranslate2 translator: upper-cases every sentence and counts the calls."""
    calls = 0

    def translate_batch(self, tokens, **kw):
        _FakeEngine.calls += 1

        class R:
            def __init__(self, t):
                self.hypotheses = [[p.upper() for p in t]]
        return [R(t) for t in tokens]


class _FakeSp:
    def encode(self, s, out_type=str):
        return [s]

    def decode_pieces(self, pieces):
        return "".join(pieces)


def test_translate_many_is_one_engine_call_and_regroups_per_text(monkeypatch):
    from screen_translator import packs
    monkeypatch.setattr(packs, "_load", lambda pair: (_FakeEngine(), _FakeSp(), ""))
    _FakeEngine.calls = 0
    out = packs.translate_many(["Hello there. How are you?", "Bye.", ""], "en", "xx")
    assert _FakeEngine.calls == 1
    assert out == ["HELLO THERE. HOW ARE YOU?", "BYE.", ""]


def test_translate_many_matches_translate(monkeypatch):
    from screen_translator import packs, translator as t
    monkeypatch.setattr(packs, "_load", lambda pair: (_FakeEngine(), _FakeSp(), ""))
    monkeypatch.setattr(t, "missing_pairs", lambda *a: [])
    texts = ["The weather is nice today.", "Please restart the computer.", "Settings"]
    args = ("en", "ja", "en-US", [], True, False)
    one = [t.Translator().translate(x, *args) for x in texts]
    assert t.Translator().translate_many(texts, *args) == one


def test_space_before_cjk_punctuation_is_removed(monkeypatch):
    from screen_translator import packs

    class Sp(_FakeSp):
        def decode_pieces(self, pieces):
            return "你好 。"
    monkeypatch.setattr(packs, "_load", lambda pair: (_FakeEngine(), Sp(), ""))
    assert packs.translate_many(["Hello."], "en", "zt") == ["你好。"]


def test_a_looping_translation_is_dropped():
    from screen_translator.translator import Translator
    assert Translator._finish("This is a long enough sentence.", "立立立立立立立立", {}, "zh-TW") is None
    assert Translator._finish("Hello there, world.", "你好，世界。", {}, "zh-TW") == "你好，世界。"


def test_translation_engine_loads_before_the_ocr_modules():
    """Loading CTranslate2 after the WinRT OCR has run crashes the process, so the app must import it first."""
    import os
    import subprocess
    import sys
    code = ("import sys, screen_translator.app\n"
            "names = list(sys.modules)\n"
            "print(names.index('ctranslate2') < min(i for i, n in enumerate(names) if n.startswith('winrt')))")
    env = dict(os.environ, PYTHONPATH="src", QT_QPA_PLATFORM="offscreen")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env, timeout=120)
    assert out.stdout.strip() == "True", out.stderr[-500:]
