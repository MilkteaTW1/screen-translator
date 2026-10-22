import json
import re
from pathlib import Path

import pytest

from screen_translator import i18n

SRC = Path(i18n.__file__).parent
FILES = sorted(i18n.BUILTIN_DIR.glob("*.json"))
HOLES = re.compile(r"\{(\w+)\}")


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.stem)
def test_every_locale_file_is_valid_and_keeps_the_placeholders(path):
    english, mine = read(i18n.BUILTIN_DIR / "en.json"), read(path)
    assert mine.get("_name"), "needs a _name written in its own language"
    for key, text in mine.items():
        assert key in english, f"unknown key {key}"
        assert set(HOLES.findall(text)) == set(HOLES.findall(english[key])), f"{key}: placeholders differ from en.json"


def test_every_key_the_code_asks_for_exists_in_english():
    english = read(i18n.BUILTIN_DIR / "en.json")
    used = set()
    for py in SRC.glob("*.py"):
        used |= set(re.findall(r"""\bt\(\s*["'](\w+)["']""", py.read_text(encoding="utf-8")))
        used |= set(re.findall(r"""_text\([^,]+,\s*["'](\w+)["']""", py.read_text(encoding="utf-8")))
        used |= set(re.findall(r"""_(?:check|row|tab)\(\s*(?:\w+,\s*)?["'](\w+)["']""", py.read_text(encoding="utf-8")))
    assert not [k for k in used if k not in english], [k for k in used if k not in english]


def test_pick_prefers_the_exact_language_then_the_same_base_language():
    codes = ["en", "zh-TW", "pt-BR"]
    assert i18n.pick("zh-TW", codes) == "zh-TW"
    assert i18n.pick("zh-CN", codes) == "zh-TW"  # closest available
    assert i18n.pick("pt-PT", codes) == "pt-BR"
    assert i18n.pick("fr-FR", codes) == "en"
    assert i18n.pick("", codes) == "en"


def test_missing_keys_fall_back_to_english(tmp_path, monkeypatch):
    (tmp_path / "xx.json").write_text(json.dumps({"_name": "Test", "tab_speech": "GO"}), encoding="utf-8")
    monkeypatch.setattr(i18n, "USER_DIR", tmp_path)
    assert i18n.load("xx") == "xx"
    assert i18n.t("tab_speech") == "GO"
    assert i18n.t("tab_general") == "General"  # not translated in xx.json
    assert ("xx", "Test") in i18n.available()
    i18n.load("en")


def test_the_language_follows_windows_unless_chosen(monkeypatch):
    monkeypatch.setattr(i18n, "system_language", lambda: "zh-TW")
    assert i18n.load("") == "zh-TW"
    assert i18n.load("en") == "en"
    i18n.load("en")
