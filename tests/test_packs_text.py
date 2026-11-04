from screen_translator import packs


def test_simplified_characters_become_traditional():
    assert packs.traditional("新闻 维护 柜台后面") == "新聞 維護 櫃檯後面"


def test_chinese_gets_chinese_punctuation_and_no_spaces_between_characters():
    assert packs.tidy_chinese("你好, 世界 .") == "你好，世界。"
    assert packs.tidy_chinese("發現了 之前未知的物種") == "發現了之前未知的物種"
    assert packs.tidy_chinese("共 1,000 個") == "共 1,000 個"
    assert packs.tidy_chinese("Hello, world.") == "Hello, world."


def test_a_sentence_cut_off_at_a_comma_is_translated_clause_by_clause(monkeypatch):
    calls = []

    def fake_run(translator, sp, prefix, sentences):
        calls.append(list(sentences))
        return ["甲，" if "," in s else s.upper() for s in sentences] if len(calls) == 1 else [s.upper() for s in sentences]

    monkeypatch.setattr(packs, "_load", lambda pair: (None, type("S", (), {})(), ""))
    monkeypatch.setattr(packs, "_run", fake_run)
    out = packs.translate_many(["first part, second part"], "en", "ja")
    assert calls[1] == ["first part,", "second part"]
    assert out == ["FIRST PART, SECOND PART"]


def test_mainland_wording_becomes_taiwan_wording():
    assert packs.taiwan_words("在設置裡單擊內存，運行應用程序") == "在設定裡點選記憶體，執行應用程式"
    assert packs.taiwan_words("本周三") == "本週三"
    assert packs.traditional("在设置里增加内存") == "在設定裡增加記憶體"


def test_phone_and_computer_use_the_same_word_table():
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent
    assert (root / "src/screen_translator/tw_words.tsv").read_bytes() == \
        (root / "android/app/src/main/assets/tw_words.tsv").read_bytes()


def test_output_that_repeats_itself_is_dropped():
    assert packs._runaway("維護" + "文將" * 30)
    assert packs._runaway("a" * 12)
    assert not packs._runaway("這是一個正常的句子，沒有重複。")
    assert not packs._runaway("哈哈哈")  # a short laugh is not a runaway
