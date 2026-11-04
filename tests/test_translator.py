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


def test_google_is_first_and_offline_is_the_backup(monkeypatch):
    from screen_translator import translator as t
    tr = t.Translator()
    tr.google = True
    monkeypatch.setattr(t, "google_translate", lambda text, *a: "你好，世界。")
    assert tr.translate("Hello there, world.", "en", "zh-TW", "en-US", [], True, False) == "你好，世界。"
    assert tr.engine == "google"
    tr.clear()

    def down(*a):
        raise OSError("no internet")
    monkeypatch.setattr(t, "google_translate", down)
    monkeypatch.setattr(tr, "_argos_many", lambda texts, *a: ["離線翻譯。"] * len(texts))
    assert tr.translate("Hello there, world.", "en", "zh-TW", "en-US", [], True, False) == "離線翻譯。"
    assert tr.engine == "offline"
    tr.clear()
    assert tr.translate("Hello there, again.", "en", "zh-TW", "en-US", [], True, False) == "離線翻譯。"  # Google is skipped for a while


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


FEED_SENTENCES = [  # real lines from a social feed: a mention, a hashtag or capitals must not make a sentence "not source"
    "We've been improving the #JetpackCompose documentation with loads of small fixes, but also new docs in general!",
    "Donald J. Trump TO THE GREAT PEOPLE OF ALABAMA, MAKE A PLAN TO VOTE FOR:",
    "Katherine Robertson for Attorney General",
    "LIVE: President Trump Holds a Rally in Sioux City, IA 10/22/26",
    "grok @bot 0.75.2 is out!",
]
FEED_NOISE = ["developer.android.com/develop/ui/com...", "@real... CJ", "Donald J. Trump @realDonal... 2", "249 754 2.8K 579K",
              "Rebecca Franks"]


def test_sentences_that_mention_a_handle_or_use_capitals_are_still_source():
    for text in FEED_SENTENCES:
        assert looks_like_source(text, "en-US", 600, 40), text


def test_links_handles_counters_and_names_are_still_not_source():
    for text in FEED_NOISE:
        assert not looks_like_source(text, "en-US", 300, 40), text


def test_a_chosen_translation_replaces_the_term_and_keeps_the_sentence():
    text = "Whisper and translation used to share one thread, so every live update waited."
    protected, originals = protect(text, ["thread = 執行緒", "live update=即時更新"], "en", False, False)
    assert "thread" not in protected and "live update" not in protected.lower()
    assert originals == ["執行緒", "即時更新"]
    assert restore(protected.replace("share one", "共用一個"), originals).count("執行緒") == 1


def test_a_chosen_translation_matches_whole_words_and_plurals_only():
    protected, originals = protect("Threading and threads", ["thread=執行緒"], "en", False, False)
    assert originals == ["執行緒"] and "Threading" in protected


def test_rows_of_dots_read_as_letters_are_not_text():
    from screen_translator.translator import looks_like_source
    assert not looks_like_source("oooooooooooooooooooo oooooooooooooooooooo", "en-US")
    assert not looks_like_source("oOo0o oo0oo OOOo0", "en-US")
    assert looks_like_source("The river trail is closed north of the old bridge", "en-US")


def _google_tr(monkeypatch, answer):
    import screen_translator.translator as t
    tr = t.Translator()
    tr.google = True
    monkeypatch.setattr(t, "google_translate", answer)
    monkeypatch.setattr(tr, "_argos_many", lambda texts, *a: [None] * len(texts))
    return t, tr


def test_one_failed_request_costs_seconds_and_says_why(monkeypatch):
    def down(*a):
        raise OSError("timeout")
    t, tr = _google_tr(monkeypatch, down)
    tr.translate("Hello there, world.", "en", "zh-TW", "en-US", [], True, False)
    assert tr.google_state() == "unreachable"
    assert tr._google_down - t.time.monotonic() <= 5.0
    tr._google_down = 0.0
    assert tr.google_state() == "ok"  # the wait is over: Google will be tried, so the status must not say offline


def test_too_many_requests_backs_off_step_by_step_and_a_success_resets_it(monkeypatch):
    import screen_translator.translator as tmod

    def limited(*a):
        raise tmod.RateLimited("429")
    t, tr = _google_tr(monkeypatch, limited)
    tr.translate("Hello there, world.", "en", "zh-TW", "en-US", [], True, False)
    assert tr.google_state() == "limited" and tr._google_down - t.time.monotonic() <= 60.0
    tr._google_down = 0.0
    tr.translate("Hello there, again.", "en", "zh-TW", "en-US", [], True, False)
    assert 60.0 < tr._google_down - t.time.monotonic() <= 120.0
    tr._google_down = 0.0
    monkeypatch.setattr(t, "google_translate", lambda text, *a: "你好")
    assert tr.translate("Hello once more.", "en", "zh-TW", "en-US", [], True, False) == "你好"
    assert tr._limits == 0 and tr.google_state() == "ok"


def test_a_redirect_to_the_unusual_traffic_page_is_a_refusal_not_a_lost_connection(monkeypatch):
    import screen_translator.translator as t

    class Answer:
        status = 302

        def read(self):
            return b""

    class Conn:
        made = 0

        def __init__(self, *a, **k):
            Conn.made += 1

        def request(self, *a):
            pass

        def getresponse(self):
            return Answer()

        def close(self):
            pass
    monkeypatch.setattr(t.http.client, "HTTPSConnection", Conn)
    t._google_conn.conn = None
    with __import__("pytest").raises(t.RateLimited):
        t.google_translate("Hello there", "en", "zh-TW")
    assert Conn.made == 1  # not asked twice
    tr = t.Translator()
    tr.google = True
    monkeypatch.setattr(tr, "_argos_many", lambda texts, *a: [None] * len(texts))
    tr.translate_many(["Hello there, world.", "Another sentence here."], "en", "zh-TW", "en-US", [], False, False)
    assert tr.google_state() == "limited"


def test_while_refused_only_one_request_finds_out_if_google_answers_again(monkeypatch):
    import screen_translator.translator as t
    calls = []

    def refused(texts, *a):
        calls.append(texts)
        raise t.RateLimited("302")
    monkeypatch.setattr(t, "google_translate_group", refused)
    tr = t.Translator()
    tr.google = True
    tr._limits = 1
    monkeypatch.setattr(tr, "_argos_many", lambda texts, *a: [None] * len(texts))
    texts = [f"This is sentence number {i} about the river." for i in range(40)]
    tr.translate_many(texts, "en", "zh-TW", "en-US", [], False, False)
    assert len(calls) == 1


def _cached_tr(monkeypatch, tmp_path, answer):
    import screen_translator.translator as t
    tr = t.Translator()
    tr.google = True
    tr.disk = t.DiskCache(tmp_path / "translations.jsonl")
    monkeypatch.setattr(t, "google_translate", answer)
    return t, tr


def test_text_read_again_after_a_restart_is_not_sent_again(monkeypatch, tmp_path):
    sent = []

    def google(text, *a):
        sent.append(text)
        return "你好,世界。"
    t, tr = _cached_tr(monkeypatch, tmp_path, google)
    assert tr.translate("Hello there, world.", "en", "zh-TW", "en-US", [], False, False) == "你好,世界。"
    assert len(sent) == 1
    fresh = t.Translator()  # the app started again
    fresh.google = True
    fresh.disk = t.DiskCache(tmp_path / "translations.jsonl")
    assert fresh.translate("Hello  there,\nworld.", "en", "zh-TW", "en-US", [], False, False) == "你好,世界。"
    assert len(sent) == 1


def test_a_different_glossary_or_target_is_translated_again(monkeypatch, tmp_path):
    sent = []

    def google(text, *a):
        sent.append(text)
        return "你好,世界。"
    t, tr = _cached_tr(monkeypatch, tmp_path, google)
    tr.translate("Hello there, world.", "en", "zh-TW", "en-US", [], False, False)
    tr.clear()
    tr.translate("Hello there, world.", "en", "zh-TW", "en-US", ["world = 世間"], False, False)
    tr.clear()
    tr.translate("Hello there, world.", "en", "ja", "en-US", [], False, False)
    assert len(sent) == 3


def test_offline_translations_are_not_remembered_on_disk(monkeypatch, tmp_path):
    def down(*a):
        raise OSError("no internet")
    t, tr = _cached_tr(monkeypatch, tmp_path, down)
    monkeypatch.setattr(tr, "_argos_many", lambda texts, *a: ["離線翻譯。"] * len(texts))
    assert tr.translate("Hello there, world.", "en", "zh-TW", "en-US", [], False, False) == "離線翻譯。"
    assert not (tmp_path / "translations.jsonl").exists()


def test_a_damaged_cache_file_only_loses_the_damaged_line_and_clear_deletes_it(tmp_path):
    import screen_translator.translator as t
    path = tmp_path / "translations.jsonl"
    c = t.DiskCache(path)
    c.put("Hello", "en", "zh-TW", 1, "你好")
    with path.open("a", encoding="utf-8") as f:
        f.write('["en|cut off')
    again = t.DiskCache(path)
    assert again.get("Hello", "en", "zh-TW", 1) == "你好"
    again.clear()
    assert not path.exists() and again.get("Hello", "en", "zh-TW", 1) is None


def _server_tr(monkeypatch, answer, kind="libretranslate"):
    import screen_translator.translator as t
    tr = t.Translator()
    tr.google = False
    tr.server = {"kind": kind, "url": "http://localhost:5000", "key": "", "model": "m"}
    monkeypatch.setattr(t, "_server_json", answer)
    monkeypatch.setattr(tr, "_argos_many", lambda texts, *a: [None] * len(texts))
    return t, tr


def test_own_libretranslate_server_is_used_when_google_is_off(monkeypatch):
    sent = []

    def answer(url, payload, key=None, timeout=30):
        sent.append((url, payload))
        return {"translatedText": ["你好,世界。" for _ in payload["q"]]}
    t, tr = _server_tr(monkeypatch, answer)
    assert tr.translate("Hello there, world.", "en", "zh-TW", "en-US", [], False, False) == "你好,世界。"
    assert sent[0][0].endswith("/translate") and sent[0][1]["target"] == "zt" and tr.engine == "server"


def test_own_openai_compatible_server_answers_a_json_array(monkeypatch):
    def answer(url, payload, key=None, timeout=30):
        assert url.endswith("/chat/completions")
        return {"choices": [{"message": {"content": 'Sure:\n["你好,世界。"]'}}]}
    t, tr = _server_tr(monkeypatch, answer, "openai")
    assert tr.translate("Hello there, world.", "en", "zh-TW", "en-US", [], False, False) == "你好,世界。"


def test_a_server_that_is_down_is_left_alone_for_a_while_and_offline_takes_over(monkeypatch):
    calls = []

    def down(url, payload, key=None, timeout=30):
        calls.append(1)
        raise OSError("refused")
    t, tr = _server_tr(monkeypatch, down)
    monkeypatch.setattr(tr, "_argos_many", lambda texts, *a: ["離線翻譯。"] * len(texts))
    assert tr.translate("Hello there, world.", "en", "zh-TW", "en-US", [], False, False) == "離線翻譯。"
    tr.translate("Another sentence here, friend.", "en", "zh-TW", "en-US", [], False, False)
    assert len(calls) == 1


def test_a_server_answer_with_the_wrong_number_of_lines_is_not_used(monkeypatch):
    def answer(url, payload, key=None, timeout=30):
        return {"translatedText": ["只有一行。"]}
    t, tr = _server_tr(monkeypatch, answer)
    assert t.server_translate_group(tr.server, ["One line here.", "Two lines here."], "en", "zh-TW") is None


def test_the_server_address_must_be_http(monkeypatch):
    import screen_translator.translator as t
    import pytest
    with pytest.raises(OSError):
        t._server_json("file:///etc/passwd", {})


def _protected(text, base="en", glossary=()):
    from screen_translator.translator import protect
    return protect(text, list(glossary), base, True, False)


def test_days_and_months_are_translated_not_kept_as_names():
    protected, originals = _protected("The museum reopened on Saturday after a long break in March.")
    assert originals == [] and "Saturday" in protected and "March" in protected  # no placeholders: they go to the translator
    protected, originals = _protected("Yesterday we met Bill Gates at the office on Saturday.")
    assert originals == ["Bill Gates"]  # a real name is still kept


def test_german_nouns_are_not_taken_for_names():
    protected, originals = _protected("Wir haben gestern den Bericht an die Firma geschickt.", base="de")
    assert originals == []


def test_a_line_in_capitals_is_translated_as_words_but_chosen_terms_keep_their_form():
    protected, originals = _protected("FREE SHIPPING ON ALL ORDERS")
    assert originals == [] and protected == "free shipping on all orders"
    protected, originals = _protected("NVIDIA DRIVERS ARE READY", glossary=["NVIDIA"])
    assert originals == ["NVIDIA"] and protected.endswith("drivers are ready")
    assert _protected("The NASA team")[1] == ["NASA"]  # an acronym in a normal line is still kept


def test_two_word_buttons_are_not_taken_for_names():
    for label in ("Sign In", "Log Out", "Read More", "Contact Us"):
        assert _protected(label)[1] == [], label

def test_why_the_offline_engine_failed_is_kept_so_it_can_be_shown(monkeypatch):
    import screen_translator.translator as t
    tr = t.Translator()
    tr.google = False

    def broken(texts, *a):
        raise RuntimeError("cannot load the model")
    monkeypatch.setattr(tr, "_argos_many", broken)
    assert tr.translate("Hello there, world.", "en", "zh-TW", "en-US", [], False, False) is None
    assert "cannot load the model" in tr.offline_error


def test_the_test_translation_says_what_google_and_the_offline_engine_did(monkeypatch):
    import screen_translator.translator as t

    def refused(*a, **k):
        raise t.RateLimited("Google refused with 302")
    monkeypatch.setattr(t, "google_translate", refused)
    monkeypatch.setattr(t, "missing_pairs", lambda s, d: [("en", "zt")])
    text = t.diagnose("zh-TW")
    assert "Google: refused" in text and "302" in text and "Offline: language pack missing: en>zt" in text


def test_one_likeliest_reason_is_given_when_text_is_read_but_not_translated(monkeypatch):
    import screen_translator.translator as t
    tr = t.Translator()
    assert tr.problem() is None  # nothing went wrong
    tr.unserved = True
    tr.google = False
    tr.missing_packs = {("en", "zt")}
    assert tr.problem() == ("packs", "en>zt")
    tr.google, tr.missing_packs = True, set()
    tr._google_down, tr._limits = 1e12, 1
    assert tr.problem()[0] == "refused"
    tr._limits, tr.google_error = 0, "TimeoutError: timed out"
    assert tr.problem() == ("network", "TimeoutError: timed out")
    tr.offline_error = "RuntimeError: boom"
    assert tr.problem() == ("offline", "RuntimeError: boom")  # the engine itself broke: that comes first



from screen_translator.translator import Translator  # noqa: E402


def test_google_requests_are_budgeted_and_the_rest_goes_offline():
    tr = Translator()
    tr.GOOGLE_BUDGET = 3
    assert tr._google_slots(2) == 2
    assert tr._google_slots(5) == 1  # only one left in the window
    assert tr._google_slots(1) == 0
    tr._google_sent = [t - tr.GOOGLE_WINDOW - 1 for t in tr._google_sent]  # the window has passed
    assert tr._google_slots(2) == 2


def test_a_draft_asks_nobody_and_is_not_remembered(monkeypatch):
    tr = Translator()
    tr.google = True
    calls = []
    monkeypatch.setattr(tr, "_google_many", lambda *a, **k: calls.append(a) or {})
    monkeypatch.setattr(tr, "_argos_many", lambda texts, src, dst: ["譯:" + t for t in texts])
    out = tr.translate("hello there friend", "en", "zh-TW", "en", [], False, False, online=False)
    assert out == "譯:hello there friend" and not calls
    assert ("hello there friend", "en", "zh-TW") not in tr.cache
