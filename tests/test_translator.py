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
