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
    monkeypatch.setattr(tr, "_argos", lambda *a: "離線翻譯。")
    assert tr.translate("Hello there, world.", "en", "zh-TW", "en-US", [], True, False) == "離線翻譯。"
    assert tr.engine == "offline"
