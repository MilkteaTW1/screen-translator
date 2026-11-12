"""Small pure functions the rest of the app leans on: language codes, glossary lines, placeholders, settings,
the update check and the streaming-speech helpers. Also regression tests for two fixed bugs."""
import io
import json

import pytest

from screen_translator import i18n, streaming, updater
from screen_translator import translator as t


# --- regression: the local Google budget is not a Google failure ------------------------------------------------

def test_a_used_up_budget_does_not_back_off_google_or_blame_the_network(monkeypatch):
    calls = []
    monkeypatch.setattr(t, "google_translate", lambda text, *a: calls.append(text) or "你好")
    tr = t.Translator()
    tr.google = True
    monkeypatch.setattr(tr, "_argos_many", lambda texts, *a: [None] * len(texts))
    tr.GOOGLE_BUDGET = 0  # every request this minute is already spent
    assert tr.translate("Hello there, world.", "en", "zh-TW", "en-US", [], True, False) is None
    assert calls == []  # nothing was sent
    assert tr._fails == 0 and tr.google_state() == "ok"  # Google did not fail: it was not asked
    tr.google_error = "TimeoutError: timed out"  # even after an earlier failure
    assert (tr.problem() or ("",))[0] != "network"  # the user is not told the internet is down


# --- regression: a locale without macOS wording stays in its own language on a Mac -------------------------------

def test_on_a_mac_a_locale_without_mac_keys_is_not_replaced_by_english(tmp_path, monkeypatch):
    english = json.loads((i18n.BUILTIN_DIR / "en.json").read_text(encoding="utf-8"))
    mac_key = next(k for k in english if k.endswith("_mac"))
    plain = mac_key[:-len("_mac")]
    (tmp_path / "xx.json").write_text(json.dumps({"_name": "Test", plain: "MINE"}), encoding="utf-8")
    monkeypatch.setattr(i18n, "USER_DIR", tmp_path)
    monkeypatch.setattr(i18n, "IS_MAC", True)
    i18n.load("xx")
    assert i18n.t(plain) == "MINE"  # was: the English macOS text
    i18n.load("en")
    assert i18n.t(plain) == english[mac_key]  # English on a Mac still gets its macOS wording
    monkeypatch.setattr(i18n, "IS_MAC", False)
    assert i18n.t(plain) == english[plain]


def test_placeholders_are_filled_and_a_bad_one_does_not_crash(tmp_path, monkeypatch):
    (tmp_path / "xx.json").write_text(json.dumps({"_name": "T", "a": "hi {name}", "b": "oops {"}), encoding="utf-8")
    monkeypatch.setattr(i18n, "USER_DIR", tmp_path)
    i18n.load("xx")
    assert i18n.t("a", name="Ann") == "hi Ann"
    assert i18n.t("b", name="Ann") == "oops {"
    assert i18n.t("no_such_key") == "no_such_key"


def test_a_number_in_a_locale_file_falls_back_to_english(tmp_path, monkeypatch):
    (tmp_path / "xx.json").write_text(json.dumps({"_name": "T", "tab_general": 5}), encoding="utf-8")
    monkeypatch.setattr(i18n, "USER_DIR", tmp_path)
    i18n.load("xx")
    assert i18n.t("tab_general") == "General"


# --- language codes ---------------------------------------------------------------------------------------------

@pytest.mark.parametrize("tag, code", [
    ("en-US", "en"), ("ja", "ja"), ("zh-Hans-CN", "zh-CN"), ("zh-Hant-TW", "zh-TW"), ("zh-TW", "zh-TW"),
    ("zh-HK", "zh-TW"), ("zh-MO", "zh-TW"), ("zh-CN", "zh-CN"), ("xx-YY", "auto"),
])
def test_ocr_tags_map_to_translation_codes(tag, code):
    assert t.ocr_tag_to_code(tag, set(t.LANGUAGES.values())) == code


def test_argos_codes_and_pairs():
    assert t.argos_code("zh-TW") == "zt" and t.argos_code("zh-CN") == "zh" and t.argos_code("pt-BR") == "pt"
    assert t.needed_pairs("en", "en") == [] and t.needed_pairs("auto", "ja") == []
    assert t.needed_pairs("fr", "en") == [("fr", "en")]


def test_language_names_for_the_prompt():
    assert t.language_name("zh-TW") == "Chinese (Traditional)"
    assert t.language_name("zh") == "Chinese (Simplified)"
    assert t.language_name("xx") == "Xx"


# --- glossary and placeholders ----------------------------------------------------------------------------------

@pytest.mark.parametrize("line, expected", [
    ("NVIDIA", ("NVIDIA", None)), ("thread = 執行緒", ("thread", "執行緒")), ("cache->快取", ("cache", "快取")),
    ("bus → 匯流排", ("bus", "匯流排")), ("  spaced  ", ("spaced", None)), ("= nothing", ("= nothing", None)),
])
def test_glossary_lines(line, expected):
    assert t.split_term(line) == expected


def test_restore_ignores_unknown_placeholders_and_tidies_spaces():
    assert t.restore("Z0Z  says  hi to Z 1 Z", ["Ann", "Bob"]) == "Ann says hi to Bob"
    assert t.restore("Z5Z is here", ["Ann"]) == "Z5Z is here"


def test_glossary_term_is_kept_through_a_translation():
    protected, originals = t.protect("Install NVIDIA drivers today.", ["NVIDIA"], "en", False, False)
    assert "NVIDIA" not in protected and originals == ["NVIDIA"]
    assert t.restore(protected.replace("Install", "安裝"), originals).startswith("安裝 NVIDIA")


def test_finish_rejects_echoes_non_cjk_output_and_loops():
    finish = t.Translator._finish
    assert finish("Hello world", "hello world", [], "fr") is None  # nothing was translated
    assert finish("Hello world", "Bonjour", [], "zh-TW") is None  # Chinese wanted, none came back
    assert finish("Hello world", "你好" + "好" * 10, [], "zh-TW") is None  # the offline model looped
    assert finish("Hello world", "你好世界", [], "zh-TW") == "你好世界"
    assert finish("Hello world", None, [], "zh-TW") is None


# --- the user's own server --------------------------------------------------------------------------------------

def test_server_settings():
    assert t.server_from_settings({}) is None
    assert t.server_from_settings({"server_kind": "gemini", "server_key": "  "}) is None
    gem = t.server_from_settings({"server_kind": "gemini", "server_key": "k"})
    assert gem["first"] and gem["model"] == t.GEMINI_MODELS[0] and gem["fallbacks"] == t.GEMINI_MODELS[1:]
    chosen = t.server_from_settings({"server_kind": "gemini", "server_key": "k", "server_model": "m"})
    assert chosen["model"] == "m" and chosen["fallbacks"] == []
    assert t.server_from_settings({"server_kind": "deepl", "server_key": "abc:fx"})["url"] == "https://api-free.deepl.com"
    assert t.server_from_settings({"server_kind": "deepl", "server_key": "abc"})["url"] == "https://api.deepl.com"
    assert t.server_from_settings({"server_kind": "libretranslate", "server_url": ""}) is None
    assert t.server_from_settings({"server_kind": "libretranslate", "server_url": " http://x "})["url"] == "http://x"


def test_deepl_codes():
    assert t._deepl_code("zh-TW", True) == "ZH-HANT" and t._deepl_code("zh-CN", True) == "ZH-HANS"
    assert t._deepl_code("zh-TW", False) == "ZH"
    assert t._deepl_code("en", True) == "EN-US" and t._deepl_code("en", False) == "EN"
    assert t._deepl_code("pt", True) == "PT-BR" and t._deepl_code("ja", True) == "JA"


def test_a_refusal_about_the_model_tries_the_next_model_but_a_bad_key_does_not():
    assert t.model_unavailable("HTTP 404 model not found")
    assert t.model_unavailable("HTTP 429 quota exceeded")
    assert not t.model_unavailable("HTTP 400 API key not valid")
    assert not t.model_unavailable("HTTP 500 internal")


def test_deepl_request_and_answer(monkeypatch):
    seen = {}

    def fake(url, payload, key=None, timeout=30, scheme="Bearer"):
        seen.update(url=url, payload=payload, scheme=scheme)
        return {"translations": [{"text": "你好"}, {"text": "世界"}]}
    monkeypatch.setattr(t, "_server_json", fake)
    server = {"kind": "deepl", "url": "https://api-free.deepl.com/", "key": "k:fx"}
    assert t.server_translate_group(server, ["Hello", "world"], "en", "zh-TW") == ["你好", "世界"]
    assert seen["url"] == "https://api-free.deepl.com/v2/translate" and seen["scheme"] == "DeepL-Auth-Key"
    assert seen["payload"] == {"text": ["Hello", "world"], "target_lang": "ZH-HANT", "source_lang": "EN"}


def test_an_openai_server_falls_back_to_the_next_model_and_remembers_it(monkeypatch):
    asked = []

    def fake(url, payload, key=None, timeout=30, scheme="Bearer"):
        asked.append(payload["model"])
        if payload["model"] == "old":
            raise OSError("HTTP 404 no such model")
        return {"choices": [{"message": {"content": 'Sure: ["你好"]'}}]}
    monkeypatch.setattr(t, "_server_json", fake)
    server = {"kind": "openai", "url": "http://x", "key": "", "model": "old", "fallbacks": ["new"]}
    assert t.server_translate_group(server, ["Hello"], "en", "zh-TW") == ["你好"]
    assert asked == ["old", "new"] and server["model"] == "new" and server["fallbacks"] == ["old"]


# --- the translation memory on disk -----------------------------------------------------------------------------

def test_the_disk_cache_drops_the_oldest_entries_when_full(tmp_path):
    cache = t.DiskCache(tmp_path / "c.jsonl")
    cache.MAX, cache.KEEP = 4, 2
    for i in range(5):
        cache.put(f"text {i}", "en", "zh-TW", 0, f"譯 {i}")
    again = t.DiskCache(tmp_path / "c.jsonl")
    assert again.get("text 0", "en", "zh-TW", 0) is None  # dropped
    assert again.get("text 4", "en", "zh-TW", 0) == "譯 4"  # the newest is kept
    assert again.get("text   4", "en", "zh-TW", 0) == "譯 4"  # spacing does not make it other text


# --- update check -----------------------------------------------------------------------------------------------

def test_version_numbers_compare_as_numbers():
    assert updater._version_tuple("1.10.0") > updater._version_tuple("1.9.9")
    assert updater._version_tuple("v2.0.1-beta") == (2, 0, 1)


def _release(monkeypatch, release):
    monkeypatch.setattr(updater.urllib.request, "urlopen",
                        lambda *a, **k: io.BytesIO(json.dumps(release).encode("utf-8")))


def test_a_newer_release_with_an_installer_is_offered(monkeypatch):
    name = "ScreenTranslator-Setup-9.9.9.exe" if updater.plat.IS_WIN else "ScreenTranslator-9.9.9.dmg"
    _release(monkeypatch, {"tag_name": "v9.9.9", "body": "notes",
                           "assets": [{"name": "other.zip", "browser_download_url": "u0"},
                                      {"name": name, "browser_download_url": "u1"}]})
    assert updater.check("1.0.0") == ("9.9.9", "u1", "notes")


def test_no_update_when_up_to_date_prerelease_or_offline(monkeypatch):
    _release(monkeypatch, {"tag_name": "v1.0.0", "assets": []})
    assert updater.check("1.0.0") is None
    _release(monkeypatch, {"tag_name": "v9.0.0", "prerelease": True, "assets": []})
    assert updater.check("1.0.0") is None

    def offline(*a, **k):
        raise OSError("no network")
    monkeypatch.setattr(updater.urllib.request, "urlopen", offline)
    assert updater.check("1.0.0") is None


# --- streaming speech helpers -----------------------------------------------------------------------------------

def test_streaming_text_is_put_in_sentence_case():
    assert streaming.tidy("HELLO  I AM HERE") == "Hello I am here"
    assert streaming.tidy("你好") == "你好"
    assert streaming.tidy("Already fine") == "Already fine"
    assert streaming.tidy("") == ""


def test_streaming_model_for_each_language():
    assert streaming.key_for("en") == "en"
    assert streaming.key_for("auto") == "zh-en" and streaming.key_for("zh") == "zh-en"
    assert streaming.key_for("ko") == "ko" and streaming.key_for("ja") == "multi"
    assert streaming.key_for("fr") is None  # only Whisper reads it


def test_auto_language_is_guessed_from_the_letters():
    assert streaming.guess_language("你好", "auto") == "zh"
    assert streaming.guess_language("hello", "auto") == "en"
    assert streaming.guess_language("hello", "ja") == "ja"
