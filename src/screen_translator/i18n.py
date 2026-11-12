"""Interface languages. Every language is one JSON file in the `locales` folder next to this file
(en.json is the reference; see locales/README.md to add yours). Files dropped into
%APPDATA%\\ScreenTranslator\\locales are found too, without rebuilding anything.
Missing keys fall back to English, so a half-finished translation still works."""
import json
from pathlib import Path

from .plat import IS_MAC, data_dir, system_language as _system_language

BUILTIN_DIR = Path(__file__).with_name("locales")
USER_DIR = data_dir() / "locales"
FALLBACK = "en"

_fallback = {}
_strings = {}
current = FALLBACK


def _read(path):
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _files():
    """{language code: file}; a file in the user folder replaces a built-in one."""
    files = {}
    for base in (BUILTIN_DIR, USER_DIR):
        if base.is_dir():
            for f in sorted(base.glob("*.json")):
                files[f.stem] = f
    return files


def available():
    """[(code, name in its own language)], English first, then by code."""
    names = {code: _read(f).get("_name", code) for code, f in _files().items()}
    return sorted(names.items(), key=lambda kv: (kv[0] != FALLBACK, kv[0].lower()))


def system_language():
    """The Windows display language, like 'zh-TW' (empty if it cannot be read)."""
    return _system_language()


def pick(wanted, codes):
    """The best of `codes` for a wanted tag: the same tag, else the same base language (zh-CN -> zh-TW), else English."""
    codes = list(codes)
    lower = {c.lower(): c for c in codes}
    wanted = (wanted or "").replace("_", "-")
    if wanted.lower() in lower:
        return lower[wanted.lower()]
    base = wanted.split("-")[0].lower()
    for c in codes:
        if c.split("-")[0].lower() == base:
            return c
    return FALLBACK


def load(code=""):
    """Use this language ('' = the one Windows is set to). Returns the code that was actually loaded."""
    global _fallback, _strings, current
    files = _files()
    _fallback = _read(files[FALLBACK]) if FALLBACK in files else {}
    current = pick(code or system_language(), files)
    _strings = _read(files[current]) if current in files else {}
    return current


def t(key, **values):
    """The text for `key` in the current language ({placeholders} filled from `values`)."""
    # A text may have a macOS wording, "<key>_mac". The chosen language comes first: its plain wording beats the
    # English macOS one, so a translation that has no "_mac" keys is still shown in its own language on a Mac.
    order = ((_strings, key + "_mac"), (_strings, key), (_fallback, key + "_mac"), (_fallback, key)) if IS_MAC \
        else ((_strings, key), (_fallback, key))
    text = next((table[k] for table, k in order if table.get(k)), key)
    try:
        return text.format(**values) if values else text
    except (KeyError, IndexError, ValueError):
        return text
