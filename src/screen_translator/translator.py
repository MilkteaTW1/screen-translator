"""Offline translation (Argos Translate) with proper-noun protection."""
import re

# Target languages offered in the UI: display name -> code (zh-TW / zh-CN are mapped to Argos zt / zh).
LANGUAGES = {
    "english": "en", "chinese (traditional)": "zh-TW", "chinese (simplified)": "zh-CN",
    "japanese": "ja", "korean": "ko", "french": "fr", "german": "de", "spanish": "es",
    "russian": "ru", "italian": "it", "portuguese": "pt", "thai": "th", "vietnamese": "vi",
    "indonesian": "id", "arabic": "ar",
}

SCRIPT_RE = {
    "ja": re.compile(r"[぀-ヿ一-鿿]"),
    "zh": re.compile(r"[一-鿿]"),
    "ko": re.compile(r"[가-힯]"),
    "ru": re.compile(r"[Ѐ-ӿ]"),
    "uk": re.compile(r"[Ѐ-ӿ]"),
    "bg": re.compile(r"[Ѐ-ӿ]"),
    "ar": re.compile(r"[؀-ۿ]"),
    "th": re.compile(r"[฀-๿]"),
    "he": re.compile(r"[֐-׿]"),
    "el": re.compile(r"[Ͱ-Ͽ]"),
    "hi": re.compile(r"[ऀ-ॿ]"),
}
CJK_RE = re.compile(r"[぀-ヿ㐀-鿿가-힯]")
ALLOWED_SYMBOLS =set("。、，．！？「」『』（）()・…ー〜~:：;；.,!?'\"’“”‘-—–/%&@#$+=[]<>")
KANA_RE =re.compile(r"[぀-ヿ]")
LATIN_RE =re.compile(r"[A-Za-z]{2,}")
KATAKANA_RE = re.compile(r"[ァ-ヺー]{2,}")
PLACEHOLDER_RE = re.compile(r"Z\s*(\d+)\s*Z")
LATIN_WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9'’\-]*")


def ocr_tag_to_code(tag, supported_codes):
    low = tag.lower()
    if low.startswith("zh"):
        return "zh-TW" if ("hant" in low or low.endswith(("-tw", "-hk"))) else "zh-CN"
    base = low.split("-")[0]
    return base if base in supported_codes else "auto"


def argos_code(code):
    return {"zh-CN": "zh", "zh-TW": "zt"}.get(code, code.split("-")[0])


def argos_installed():
    try:
        import argostranslate.translate as at
        return {l.code for l in at.get_installed_languages()}
    except Exception:
        return set()


def argos_pairs(installed_codes):
    """Direct (from, to) pairs implied by the installed language codes (every pack goes via English)."""
    pairs = set()
    for c in installed_codes - {"en"}:
        pairs |= {(c, "en"), ("en", c)}
    return pairs


def needed_pairs(src, dst):
    """Argos packs a translation needs: every pack goes via English."""
    a, b = argos_code(src), argos_code(dst)
    if a == b or a == "auto":
        return []
    return [(a, b)] if "en" in (a, b) else [(a, "en"), ("en", b)]


def missing_pairs(src, dst):
    return [p for p in needed_pairs(src, dst) if p not in argos_pairs(argos_installed())]


def install_pack(from_code, to_code):
    """Download and install one Argos pack (needs internet, roughly 50-100 MB). Raises on failure."""
    import argostranslate.package as package
    package.update_package_index()
    match = next((p for p in package.get_available_packages()
                  if p.from_code == from_code and p.to_code == to_code), None)
    if match is None:
        raise RuntimeError(f"no such language pack: {from_code}>{to_code}")
    package.install_from_path(match.download())


URLISH_RE = re.compile(r"https?:|www\.|\.(com|org|net|io|tw|edu|gov|co)\b|[/\\@]|\w_\w", re.IGNORECASE)


def _wordlike(token):
    t = token.strip(".,!?:;()\"'“”‘’-—…")
    return t.isdigit() or (t.isalpha() and not re.search(r"[a-z][A-Z]", t))


def looks_translatable_latin(text, skip_names):
    """Reject URLs, @handles, ids/hashes, single words and (optionally) names: they don't translate well."""
    if URLISH_RE.search(text):
        return False
    tokens = text.split()
    if sum(_wordlike(t) for t in tokens) / len(tokens) < 0.7:
        return False  # mostly ids, hashes or mixed letters and digits
    if sum(1 for t in tokens if t.strip(".,!?:;()\"'-").isalpha() and len(t.strip(".,!?:;()\"'-")) >= 3) < 2:
        return False  # a lone word or label: usually a name or a brand
    if len(tokens) >= 5 and sum(t[:1].isupper() for t in tokens) / len(tokens) >= 0.8 \
            and not text.rstrip().endswith((".", "!", "?")):
        return False  # a menu bar ("Home About Mission Donate ...")
    if skip_names and len(tokens) <= 2 and all(t[:1].isupper() for t in tokens):
        return False  # "Bill Gates", "Major Hurricane"
    return True


def looks_like_source(text, ocr_tag, w=None, h=None, skip_names=True):
    """Keep only lines that are actually in the chosen source language (w/h: line size in px)."""
    base = ocr_tag.split("-")[0].lower()
    letters = [c for c in text if c.isalpha()]
    if len(letters) < 2:
        return False
    chars = "".join(text.split())
    noise = [c for c in chars if not c.isalnum() and c not in ALLOWED_SYMBOLS]
    if noise and len(noise) / len(chars) >= 0.15:
        return False  # icons and artwork come out of OCR as strings of odd symbols
    if w and h and base in ("ja", "zh", "ko") and w < 0.6 * h * len("".join(text.split())):
        return False  # too narrow for that many characters: an icon or artwork misread as text
    if base == "ja":
        # Kanji-only lines are indistinguishable from Chinese, and OCR on Chinese text often
        # invents a stray kana, so require a real share of kana.
        kana = len(KANA_RE.findall(text))
        if kana < 2 or kana / len(letters) < 0.25:
            return False
    if base == "zh" and KANA_RE.search(text):
        return False
    pattern = SCRIPT_RE.get(base)
    if pattern:
        hits = sum(1 for c in letters if pattern.match(c))
    else:
        hits = sum(1 for c in letters if c.isascii())
        if len(LATIN_RE.findall(text)) < 1 or len(letters) < 3:
            return False
        if base == "en" and not looks_translatable_latin(text, skip_names):
            return False
    return hits / len(letters) >= 0.7  # mostly the chosen language, not OCR noise or mixed text


def _auto_proper_spans(text, base, keep_katakana):
    spans = []
    if base == "ja" and keep_katakana:
        spans += [m.span() for m in KATAKANA_RE.finditer(text)]
    if SCRIPT_RE.get(base) is None:  # latin-script sources
        words = LATIN_WORD_RE.findall(text)
        # "Open File Settings": UI text in Title Case. Those capitals are not names, and protecting
        # them would leave the line almost untranslated.
        title_case = len(words) >= 3 and sum(w[0].isupper() for w in words) / len(words) >= 0.6
        for m in LATIN_WORD_RE.finditer(text):
            w = m.group()
            before = text[: m.start()].rstrip()
            sentence_start = not before or before[-1] in ".!?:\"“"
            camel = bool(re.search(r"[a-z][A-Z]", w))
            allcaps = len(w) >= 2 and w.isupper()
            capital_mid = w[0].isupper() and not sentence_start and len(w) > 1 and not title_case
            if camel or allcaps or capital_mid:
                spans.append(m.span())
    return spans


def protect(text, glossary, base, auto, keep_katakana):
    """Swap proper nouns for placeholders. Returns (text, [originals])."""
    spans = []
    for term in sorted(glossary, key=len, reverse=True):
        for m in re.finditer(re.escape(term), text, re.IGNORECASE):
            spans.append(m.span())
    if auto:
        spans += _auto_proper_spans(text, base, keep_katakana)
    # merge overlaps, keep longest-first order by start
    spans.sort()
    merged = []
    for s, e in spans:
        # Overlapping spans, or names separated only by spaces ("Certified Online English Teacher"),
        # become one placeholder: neighbouring placeholders get glued together by the model.
        if merged and (s < merged[-1][1] or not text[merged[-1][1]:s].strip()):
            merged[-1] = (merged[-1][0], max(e, merged[-1][1]))
        else:
            merged.append((s, e))
    originals, out, pos = [], [], 0
    for s, e in merged:
        out.append(text[pos:s])
        out.append(f" Z{len(originals)}Z ")
        originals.append(text[s:e])
        pos = e
    out.append(text[pos:])
    return re.sub(r"\s+", " ", "".join(out)).strip(), originals


def restore(text, originals):
    def sub(m):
        i = int(m.group(1))
        return originals[i] if i < len(originals) else m.group()
    return re.sub(r"\s+", " ", PLACEHOLDER_RE.sub(sub, text)).strip()


class Translator:
    def __init__(self):
        self.cache = {}
        self.missing_packs = set()  # Argos packs we needed but don't have

    def _argos(self, protected, src, dst):
        """Translate offline. Returns None (and records what's missing) if packs aren't installed."""
        a, b = argos_code(src), argos_code(dst)
        missing = missing_pairs(src, dst)
        if a == "auto" or missing:
            self.missing_packs.update(missing)
            return None
        import argostranslate.translate as at
        return at.translate(protected, a, b)

    def clear(self):
        self.cache.clear()

    def translate(self, text, src, dst, ocr_tag, glossary, auto, keep_katakana):
        key = (text, src, dst)
        if key in self.cache:
            return self.cache[key]
        protected, originals = protect(text, glossary, ocr_tag.split("-")[0].lower(), auto, keep_katakana)
        remaining = PLACEHOLDER_RE.sub("", protected)
        if not any(c.isalpha() for c in remaining):
            result = None  # the line is only proper nouns / symbols: nothing to translate
        else:
            try:
                out = self._argos(protected, src, dst)
                result = restore(out, originals) if out else None
                if result and result.strip().lower() == text.strip().lower():
                    result = None
                # Target is Chinese/Japanese/Korean but nothing came out in it: not a translation.
                if result and dst.split("-")[0] in ("zh", "zt", "ja", "ko") and not CJK_RE.search(result):
                    result = None
                # The small offline model sometimes loops ("立立立立…") on long run-on text.
                if result and (re.search(r"(.){5,}", result) or len(result) > 4 * len(text) + 20):
                    result = None
            except Exception:
                return None  # don't cache failures
        self.cache[key] = result
        return result
