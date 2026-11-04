"""Translation (Google Translate, with offline Argos Translate as the backup) and proper-noun protection."""
import json
import http.client
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import zlib
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import better, packs

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


def argos_pairs(*_):
    """Direct (from, to) packs installed on this machine."""
    return set(packs.installed_pairs())


def needed_pairs(src, dst):
    """Argos packs a translation needs: every pack goes via English."""
    a, b = argos_code(src), argos_code(dst)
    if a == b or a == "auto":
        return []
    return [(a, b)] if "en" in (a, b) else [(a, "en"), ("en", b)]


def missing_pairs(src, dst):
    return [p for p in needed_pairs(src, dst) if p not in argos_pairs()]


def install_pack(from_code, to_code, progress=None):
    """Download and install one language pack (needs internet). Raises on failure."""
    packs.install(from_code, to_code, progress)


URLISH_RE = re.compile(r"https?:|www\.|\.(com|org|net|io|tw|edu|gov|co)\b|[/\\@]|\w_\w", re.IGNORECASE)


def _wordlike(token):
    t = token.strip(".,!?:;()\"'“”‘’-—…")
    return t.isdigit() or (t.isalpha() and not re.search(r"[a-z][A-Z]", t))


_OFFLINE_LOCK = threading.Lock()
FUNCTION_WORDS = {"the", "a", "an", "of", "to", "in", "on", "for", "and", "or", "is", "are", "was", "with", "at", "by",
                  "from", "this", "that", "it", "be", "we", "you", "your", "our", "not", "as", "has", "have"}


def looks_translatable_latin(text, skip_names):
    """Reject URLs, @handles, ids/hashes, single words and (optionally) names: they don't translate well.
    Judged on the words that are left once handles, hashtags and links are set aside, so a sentence that merely
    mentions one still counts as a sentence."""
    tokens = text.split()
    words = [t for t in tokens if not URLISH_RE.search(t) and not t.startswith(("@", "#"))]
    if len(words) < 2 and not (len(tokens) >= 3 and len(words) >= 1):
        return False  # a link, a handle, or one word
    if sum(_wordlike(t) for t in words) / max(1, len(words)) < 0.6:
        return False  # mostly ids, hashes or mixed letters and digits
    if sum(1 for t in words if t.strip(".,!?:;()\"'-").isalpha() and len(t.strip(".,!?:;()\"'-")) >= 3) < 2:
        return False  # a lone word or label: usually a name or a brand
    lowered = {t.strip(".,!?:;()\"'-").lower() for t in words}
    if len(words) >= 5 and not (lowered & FUNCTION_WORDS) and sum(t[:1].isupper() for t in words) / len(words) >= 0.8             and not text.rstrip().endswith((".", "!", "?")):
        return False  # a menu bar ("Home About Mission Donate ...")
    names = [t for t in words if not t.isdigit()]  # "Bill Gates", "Major Hurricane", "Donald J. Trump @handle 2h"
    if skip_names and len(names) <= (3 if len(words) < len(tokens) else 2) and all(t[:1].isupper() for t in names):
        return False
    return True


def looks_like_source(text, ocr_tag, w=None, h=None, skip_names=True):
    """Keep only lines that are actually in the chosen source language (w/h: line size in px)."""
    base = ocr_tag.split("-")[0].lower()
    letters = [c for c in text if c.isalpha()]
    if len(letters) < 2:
        return False
    chars = "".join(text.split())
    alnum = [c.lower() for c in chars if c.isalnum()]
    if len(alnum) >= 6 and len(set(alnum)) <= 3:
        return False  # a row of dots or circles reads as "oooooooo": a picture, not text
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


# Capitalised in English but ordinary words to translate: days, months, languages, nationalities.
COMMON_CAPITALISED = frozenset("""monday tuesday wednesday thursday friday saturday sunday january february march april may june july
    august september october november december english chinese japanese korean french german spanish italian russian
    portuguese arabic hindi american british european asian african canadian australian indian mexican""".split())


UI_TAILS = frozenset("in up out on off more back now us me all next here free again today".split())  # "Sign In", "Read More"


def _shouting(text):
    """A line in capitals ("FREE SHIPPING ON ORDERS"): the capitals are style, not names."""
    letters = [c for c in text if c.isalpha()]
    return len(letters) >= 5 and "_" not in text and sum(c.isupper() for c in letters) / len(letters) >= 0.9


def _auto_proper_spans(text, base, keep_katakana):
    spans = []
    if base == "ja" and keep_katakana:
        spans += [m.span() for m in KATAKANA_RE.finditer(text)]
    if SCRIPT_RE.get(base) is None:  # latin-script sources
        words = LATIN_WORD_RE.findall(text)
        # "Open File Settings": UI text in Title Case. Those capitals are not names, and protecting
        # them would leave the line almost untranslated.
        title_case = len(words) >= 3 and sum(w[0].isupper() for w in words) / len(words) >= 0.6
        title_case = title_case or (len(words) == 2 and words[0][0].isupper() and words[1][0].isupper()
                                    and words[1].lower() in UI_TAILS)  # a button, not a name
        for m in LATIN_WORD_RE.finditer(text):
            w = m.group()
            before = text[: m.start()].rstrip()
            sentence_start = not before or before[-1] in ".!?:\"“"
            camel = bool(re.search(r"[a-z][A-Z]", w))
            allcaps = len(w) >= 2 and w.isupper()
            capital_mid = (w[0].isupper() and not sentence_start and len(w) > 1 and not title_case
                           and base != "de"  # German capitalises every noun: that says nothing about names
                           and not (base == "en" and w.lower() in COMMON_CAPITALISED))
            if camel or allcaps or capital_mid:
                spans.append(m.span())
    return spans


TERM_SPLIT_RE = re.compile(r"\s*(?:=|＝|->|→)\s*")


def split_term(line):
    """A glossary line: "NVIDIA" is never translated; "thread = 執行緒" is always translated that way.
    Returns (term, forced translation or None)."""
    parts = TERM_SPLIT_RE.split(line.strip(), maxsplit=1)
    if len(parts) == 2 and parts[0] and parts[1]:
        return parts[0], parts[1]
    return line.strip(), None


def protect(text, glossary, base, auto, keep_katakana):
    """Swap proper nouns and chosen terms for placeholders. Returns (text, [what goes back in])."""
    spans = []  # (start, end, forced translation or None)
    for line in sorted(glossary, key=len, reverse=True):
        term, forced = split_term(line)
        if not term:
            continue
        # a chosen translation matches whole words (and a plural), so "thread" does not hit "threading"
        pattern = rf"(?<![A-Za-z0-9]){re.escape(term)}(?:e?s)?(?![A-Za-z0-9])" if forced and term.isascii() else re.escape(term)
        for m in re.finditer(pattern, text, re.IGNORECASE):
            spans.append((*m.span(), forced))
    if auto:
        if SCRIPT_RE.get(base) is None and _shouting(text):
            lowered = text.lower()
            if len(lowered) == len(text):  # a line in capitals reads as words, not as a row of names; chosen terms keep theirs
                keep = [False] * len(text)
                for s, e, _forced in spans:
                    keep[s:e] = [True] * (e - s)
                text = "".join(c if k else low for c, low, k in zip(text, lowered, keep))
        spans += [(s, e, None) for s, e in _auto_proper_spans(text, base, keep_katakana)]
    # merge overlaps, keep longest-first order by start
    spans.sort(key=lambda sp: (sp[0], -sp[1]))
    merged = []  # [start, end, [forced pieces (start, end, translation)]]
    for s, e, forced in spans:
        # Overlapping spans, or names separated only by spaces ("Certified Online English Teacher"),
        # become one placeholder: neighbouring placeholders get glued together by the model.
        if merged and (s < merged[-1][1] or not text[merged[-1][1]:s].strip()):
            merged[-1][1] = max(e, merged[-1][1])
            if forced and not any(p[0] < e and s < p[1] for p in merged[-1][2]):
                merged[-1][2].append((s, e, forced))
        else:
            merged.append([s, e, [(s, e, forced)] if forced else []])
    originals, out, pos = [], [], 0
    for s, e, pieces in merged:
        out.append(text[pos:s])
        out.append(f" Z{len(originals)}Z ")
        shown = text[s:e]
        for ps, pe, forced in sorted(pieces, reverse=True):  # the chosen translations replace their source words
            shown = shown[:ps - s] + forced + shown[pe - s:]
        originals.append(shown)
        pos = e
    out.append(text[pos:])
    return re.sub(r"\s+", " ", "".join(out)).strip(), originals


def restore(text, originals):
    def sub(m):
        i = int(m.group(1))
        return originals[i] if i < len(originals) else m.group()
    return re.sub(r"\s+", " ", PLACEHOLDER_RE.sub(sub, text)).strip()


def language_name(code):
    names = {v: k for k, v in LANGUAGES.items()}
    return names.get(code, names.get({"zh": "zh-CN"}.get(code, code), code)).title()


class RateLimited(OSError):
    """Google refuses for now: "too many requests", or a redirect to its "unusual traffic" page."""


REFUSED = {301, 302, 303, 307, 403, 429, 503}  # the network is fine, Google does not want to answer this machine
_GOOGLE_POOL = ThreadPoolExecutor(max_workers=2)  # few requests at a time, on threads that keep their connection open


_google_conn = threading.local()  # one kept-open connection per thread: no new TLS handshake for every request


def google_translate(text, src, dst, timeout=8):
    """Google Translate (the free web endpoint). The text is sent to Google."""
    path = "/translate_a/single?" + urllib.parse.urlencode(
        {"client": "gtx", "sl": "auto" if src == "auto" else src, "tl": dst, "dt": "t"})
    body = urllib.parse.urlencode({"q": text})
    headers = {"User-Agent": "Mozilla/5.0", "Content-Type": "application/x-www-form-urlencoded"}
    for attempt in (0, 1):
        conn = getattr(_google_conn, "conn", None)
        if conn is None:
            conn = _google_conn.conn = http.client.HTTPSConnection("translate.googleapis.com", timeout=timeout)
        try:
            conn.request("POST", path, body, headers)
            resp = conn.getresponse()
            raw = resp.read()
            if resp.status in REFUSED:
                raise RateLimited(f"Google refused with {resp.status}")
            if resp.status != 200:
                raise OSError(f"Google answered {resp.status}")
            break
        except RateLimited:
            conn.close()
            _google_conn.conn = None
            raise  # asking again at once only makes it worse
        except Exception:
            conn.close()
            _google_conn.conn = None  # a stale kept-open connection: retry once on a fresh one
            if attempt:
                raise
    data = json.loads(raw)
    return "".join(part[0] for part in data[0] if part and part[0])


def google_translate_group(texts, src, dst):
    """Several short texts in one request (one per line): far fewer round trips. None if the lines don't come back 1:1."""
    out = google_translate("\n".join(" ".join(t.split()) for t in texts), src, dst)
    lines = out.split("\n")
    return lines if len(lines) == len(texts) else None


def _server_json(url, payload, key=None, timeout=30):
    """POST JSON to the user's own translation server and return the decoded answer."""
    if not url.lower().startswith(("http://", "https://")):
        raise OSError("the server address must start with http:// or https://")
    headers = {"Content-Type": "application/json", "User-Agent": "ScreenTranslator"}
    if key:
        headers["Authorization"] = "Bearer " + key
    req = urllib.request.Request(url, json.dumps(payload).encode("utf-8"), headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:  # the server says why (wrong key, unknown model, quota): that is what the user needs to read
        try:
            said = e.read().decode("utf-8", "replace")
        except Exception:
            said = ""
        try:  # most servers wrap it as {"error": {"message": ...}} (Gemini: in a list)
            data = json.loads(said)
            data = data[0] if isinstance(data, list) and data else data
            said = str(data["error"]["message"])
        except Exception:
            pass
        raise OSError(f"HTTP {e.code} {said.strip()[:200]}") from None


# Gemini through its OpenAI-compatible address: the user's own key, which is theirs to keep and to be billed (or not) for.
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/openai"
# Google retires and restricts models (2.5 ones are now only for past users): the first is tried, then the next
# one when Google says the model does not exist, is not open to this key, or its quota is used up.
GEMINI_MODELS = ["gemini-3.5-flash-lite", "gemini-3.6-flash", "gemini-3.1-flash-lite", "gemini-2.5-flash-lite"]
GEMINI_MODEL = GEMINI_MODELS[0]


def server_from_settings(s):
    """The own-server setting as the translator wants it ({kind, url, key, model, first}), or None when there is none."""
    kind, url, key = s.get("server_kind", "off"), s.get("server_url", "").strip(), s.get("server_key", "")
    if kind == "gemini":  # the user's own Gemini key: the address and model are known, the key is theirs
        return {"kind": "openai", "url": GEMINI_URL, "key": key, "model": s.get("server_model", "") or GEMINI_MODEL,
                "fallbacks": [] if s.get("server_model", "") else GEMINI_MODELS[1:], "first": True} if key.strip() else None
    return {"kind": kind, "url": url, "key": key, "model": s.get("server_model", "")} if kind != "off" and url else None


def model_unavailable(error):
    """The server's refusal is about the model (unknown, not open to this key, quota used up), not the key itself:
    another model may still work."""
    low = error.lower()
    if "api key" in low or "api_key" in low:
        return False
    return error.startswith(("HTTP 404", "HTTP 403", "HTTP 429", "HTTP 400"))


def _libre_code(code):
    return {"zh-CN": "zh", "zh-TW": "zt"}.get(code, code.split("-")[0])


def server_translate_group(server, texts, src, dst):
    """Several lines through the user's own server (LibreTranslate, or an OpenAI-compatible one such as Ollama
    or LM Studio). Returns one translation per line, or None if they don't come back 1:1."""
    base = server["url"].rstrip("/")
    lines = [" ".join(t.split()) for t in texts]
    if server["kind"] == "libretranslate":
        answer = _server_json(base + "/translate", {
            "q": lines, "source": "auto" if src == "auto" else _libre_code(src), "target": _libre_code(dst),
            "format": "text", "api_key": server.get("key", "")}, timeout=20)
        out = answer.get("translatedText")
        out = [out] if isinstance(out, str) else out
    else:
        prompt = (f"Translate each string in this JSON array into {language_name(dst)}. Answer with only a JSON array "
                  f"of the same length, in the same order, nothing else.\n" + json.dumps(lines, ensure_ascii=False))
        answer = None
        models = [server.get("model", "")] + list(server.get("fallbacks", []))
        for i, model in enumerate(models):
            try:
                answer = _server_json(base + "/chat/completions", {
                    "model": model, "temperature": 0, "stream": False,
                    "messages": [{"role": "user", "content": prompt}]}, server.get("key"), timeout=60)
            except OSError as e:
                if i == len(models) - 1 or not model_unavailable(str(e)):
                    raise
                continue
            server["model"], server["fallbacks"] = model, [m for m in models if m != model]  # what worked is asked first next time
            break
        content = answer["choices"][0]["message"]["content"]
        start, end = content.find("["), content.rfind("]")
        out = json.loads(content[start:end + 1])
    if isinstance(out, list) and len(out) == len(texts) and all(isinstance(o, str) for o in out):
        return out
    return None


class DiskCache:
    """Google's translations kept in a file, so text read again (today or next week) is not sent again.
    Only Google's: a translation from the small offline model should not outlive the moment Google is back."""
    MAX = 50000  # entries; past this the oldest are dropped
    KEEP = 30000

    def __init__(self, path):
        self.path = Path(path)
        self._items = None  # loaded on first use
        self._lock = threading.Lock()

    @staticmethod
    def _key(text, src, dst, sig):
        return f"{src}|{dst}|{sig}|{' '.join(text.split())}"  # OCR's line breaks and spacing do not make it other text

    def _load(self):
        if self._items is not None:
            return
        self._items = {}
        try:
            with self.path.open(encoding="utf-8") as f:
                for line in f:
                    try:
                        key, value = json.loads(line)
                        self._items[key] = value
                    except (ValueError, TypeError):
                        continue  # a line cut off by a crash: the rest is still good
        except OSError:
            pass

    def get(self, text, src, dst, sig):
        with self._lock:
            self._load()
            return self._items.get(self._key(text, src, dst, sig))

    def put(self, text, src, dst, sig, translation):
        key = self._key(text, src, dst, sig)
        with self._lock:
            self._load()
            self._items[key] = translation
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                if len(self._items) > self.MAX:
                    self._items = dict(list(self._items.items())[-self.KEEP:])
                    lines = "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in self._items.items())
                    self.path.write_text(lines, encoding="utf-8")
                else:
                    with self.path.open("a", encoding="utf-8") as f:
                        f.write(json.dumps([key, translation], ensure_ascii=False) + "\n")
            except OSError:
                pass  # no room or no rights: it still works, just without remembering

    def clear(self):
        with self._lock:
            self._items = {}
            try:
                self.path.unlink(missing_ok=True)
            except OSError:
                pass


class Translator:
    RETRY_AFTER = 30.0  # longest wait before trying Google again after it failed; one slow answer costs only a few seconds
    RATE_LIMITED = 600.0  # longest wait after "too many requests", reached only if Google keeps saying it

    def __init__(self):
        self.cache = {}
        self._google_sent = []  # when the recent Google requests were made (monotonic seconds)
        self.google = False  # use Google Translate first, the offline engine is the fallback
        self.better = False  # the offline engine is the optional language model (when it is downloaded), not the standard packs
        self._google_down = 0.0  # Google is not tried again before this moment
        self.disk = None  # a DiskCache, if translations are to be remembered
        self.server = None  # {"kind", "url", "key", "model"}: the user's own server, tried after Google, before offline
        self._server_down = 0.0
        self.server_error = None  # why the user's own server (Gemini) did not translate, if it did not
        self.unserved = False  # the last batch left some text without any translation
        self.google_error = None  # why the last Google request failed (None: it did not, or was not tried)
        self.offline_error = None  # why the offline engine failed, if it threw (a missing pack is not an error)
        self._server_fails = 0
        self._fails = 0  # failures in a row
        self._limits = 0  # "too many requests" in a row
        self.missing_packs = set()  # Argos packs we needed but don't have
        self.engine = None  # engine used for the most recent translation (None: nothing translated yet)

    def _argos_many(self, texts, src, dst):
        """Translate offline, all texts in one batch. Returns None per text (and records what's missing) if packs aren't installed."""
        a, b = argos_code(src), argos_code(dst)
        if self.better and better.installed() and a != "auto":
            return texts if a == b else better.translate_many(texts, a, b)
        missing = missing_pairs(src, dst)
        if a == "auto" or missing:
            self.missing_packs.update(missing)
            return [None] * len(texts)
        for pair in needed_pairs(src, dst) or [(a, b)]:  # via English when there is no direct pack
            if pair[0] != pair[1]:
                texts = packs.translate_many(texts, *pair)
        return texts

    GOOGLE_BUDGET = 24  # Google requests allowed per GOOGLE_WINDOW seconds: more than that and it starts refusing this computer
    GOOGLE_WINDOW = 60.0

    def _google_slots(self, wanted):
        """How many of `wanted` Google requests fit in the budget right now (and counts them as made)."""
        now = time.monotonic()
        self._google_sent = [t for t in self._google_sent if now - t < self.GOOGLE_WINDOW]
        n = max(0, min(wanted, self.GOOGLE_BUDGET - len(self._google_sent)))
        self._google_sent += [now] * n
        return n

    def _google_many(self, items, src, dst):
        """{index: translation} for the items Google could do; nothing when it is unreachable."""
        if time.monotonic() < self._google_down:
            return {}

        groups, group, size = [], [], 0
        for item in items:  # lines that go in one request
            if group and (len(group) >= 8 or size + len(item[2]) > 1500):
                groups.append(group)
                group, size = [], 0
            group.append(item)
            size += len(item[2])
        if group:
            groups.append(group)
        if self._limits:
            groups = groups[:1]  # just found out whether Google answers again: one request, not a screenful
        groups = groups[:self._google_slots(len(groups))]  # a budget: what is over it is translated offline instead

        limited = []

        def one(group):
            try:
                lines = google_translate_group([g[2] for g in group], src, dst)
                if lines is not None:
                    return list(zip((g[0] for g in group), lines))
                return [(g[0], google_translate(g[2], src, dst)) for g in group]  # lines got mixed up: one by one
            except RateLimited as e:
                limited.append(1)
                self.google_error = str(e)
                return [(g[0], None) for g in group]
            except Exception as e:
                self.google_error = f"{type(e).__name__}: {e}"
                return [(g[0], None) for g in group]

        done = dict(pair for part in _GOOGLE_POOL.map(one, groups) for pair in part)
        if limited:
            self._limits += 1
            self._google_down = time.monotonic() + min(self.RATE_LIMITED, 60.0 * 2 ** (self._limits - 1))
        elif items and not any(done.values()):
            self._fails += 1
            self._google_down = time.monotonic() + min(self.RETRY_AFTER, 5.0 * self._fails)
        elif any(done.values()):
            self._fails = self._limits = 0
            self.google_error = None
        return {i: out for i, out in done.items() if out}

    def _server_many(self, items, src, dst):
        """{index: translation} for the items the user's own server could do; nothing when it is down."""
        if not self.server or time.monotonic() < self._server_down:
            return {}
        done = {}
        for start in range(0, len(items), 8):
            group = items[start:start + 8]
            try:
                lines = server_translate_group(self.server, [g[2] for g in group], src, dst)
                if lines is None:
                    self.server_error = "the answer did not have one line for each text"
            except Exception as e:
                lines = None
                self.server_error = f"{type(e).__name__}: {e}"
            if lines is None:
                break  # down, or answering nonsense: the rest goes offline rather than waiting on it again
            done.update({g[0]: out for g, out in zip(group, lines) if out})
        if done:
            self._server_fails = 0
            self.server_error = None
        else:
            self._server_fails += 1
            self._server_down = time.monotonic() + min(60.0, 10.0 * self._server_fails)
        return done

    def problem(self):
        """(kind, detail) for why text was read but not translated, or None when nothing is wrong. One answer, the
        likeliest, so the user gets one message: 'packs' (no offline pack and Google is off), 'refused' (Google says no),
        'network' (cannot reach Google), 'offline' (the offline engine broke), 'other'."""
        if not self.unserved:
            return None
        state = self.google_state()
        if self.missing_packs and state == "off":
            return "packs", ", ".join(f"{a}>{b}" for a, b in sorted(self.missing_packs))
        if self.offline_error:
            return "offline", self.offline_error
        if state == "limited":
            return "refused", ""
        if state == "unreachable":
            return "network", self.google_error or ""
        if self.missing_packs:
            return "packs", ", ".join(f"{a}>{b}" for a, b in sorted(self.missing_packs))
        return "other", self.google_error or ""

    def google_state(self):
        """Why Google is not being used right now: 'off', 'limited', 'unreachable', or 'ok' (it will be tried)."""
        if not self.google:
            return "off"
        if time.monotonic() >= self._google_down:
            return "ok"
        return "limited" if self._limits else "unreachable"

    def clear(self):
        self.cache.clear()

    def translate(self, text, src, dst, ocr_tag, glossary, auto, keep_katakana, online=True):
        return self.translate_many([text], src, dst, ocr_tag, glossary, auto, keep_katakana, online)[0]

    @staticmethod
    def _finish(text, out, originals, dst):
        result = restore(out, originals) if out else None
        if result and result.strip().lower() == text.strip().lower():
            result = None
        # Target is Chinese/Japanese/Korean but nothing came out in it: not a translation.
        if result and dst.split("-")[0] in ("zh", "zt", "ja", "ko") and not CJK_RE.search(result):
            result = None
        # The small offline model sometimes loops ("立立立立…") on long run-on text.
        if result and (re.search(r"(.)\1{5,}", result) or len(result) > 4 * len(text) + 20):
            result = None
        return result

    def translate_many(self, texts, src, dst, ocr_tag, glossary, auto, keep_katakana, online=True):
        """Translate several texts at once. The offline engine takes them in one batch, which is far faster
        than one call each (a screen full of text: 2.0 s one by one, 0.8 s batched)."""
        results = [None] * len(texts)
        todo = []  # (index, text, protected text, protected originals)
        sig = zlib.crc32(repr((sorted(glossary), auto, keep_katakana)).encode("utf-8"))  # these change what comes out
        for i, text in enumerate(texts):
            key = (text, src, dst)
            if key in self.cache:
                results[i] = self.cache[key]
                continue
            stored = self.disk.get(text, src, dst, sig) if self.disk else None
            if stored:
                results[i] = self.cache[key] = stored
                continue
            protected, originals = protect(text, glossary, ocr_tag.split("-")[0].lower(), auto, keep_katakana)
            if not any(c.isalpha() for c in PLACEHOLDER_RE.sub("", protected)):
                self.cache[key] = None  # the line is only proper nouns / symbols: nothing to translate
                continue
            todo.append((i, text, protected, originals))
        outs = {}
        first = bool(self.server and self.server.get("first") and online)  # the user's own Gemini key goes before Google
        if first:
            outs = self._server_many(todo, src, dst)
            if outs:
                self.engine = "server"
        from_google = set()
        if self.google and online:  # online=False: a quick local draft (the sentence being spoken), no request to anyone
            pending = [item for item in todo if not outs.get(item[0])]
            got = self._google_many(pending, src, dst) if pending else {}
            if got:
                outs.update(got)
                self.engine = "google"
            from_google = {i for i, out in got.items() if out}
        rest = [item for item in todo if not outs.get(item[0])]
        if rest and self.server and online and not first:
            more = self._server_many(rest, src, dst)
            if more:
                outs.update(more)
                self.engine = "server"
            rest = [item for item in rest if not outs.get(item[0])]
        if rest:
            engine = self.engine if len(rest) < len(todo) else "offline"
            try:
                with _OFFLINE_LOCK:  # the offline engine takes one caller at a time; Google requests run side by side
                    offline = self._argos_many([item[2] for item in rest], src, dst)
                for item, out in zip(rest, offline):
                    outs[item[0]] = out
                if any(offline):
                    self.offline_error = None
            except Exception as e:
                self.offline_error = f"{type(e).__name__}: {e}"  # shown to the user: otherwise nothing says why
            self.engine = engine
        self.unserved = any(not outs.get(item[0]) for item in todo)
        for i, text, protected, originals in todo:
            if i not in outs:
                continue
            try:
                results[i] = self._finish(text, outs[i], originals, dst)
            except Exception:
                continue
            if online:  # a draft is not remembered: the finished text must still go to Google
                self.cache[(text, src, dst)] = results[i]
            if self.disk and results[i] and i in from_google:
                self.disk.put(text, src, dst, sig, results[i])
        return results


def diagnose(dst, src="en", settings=None):
    """Plain text saying what works: Google, the offline engine, the packs on disk. For the "test translation" button
    and for bug reports: the app otherwise keeps quiet about why a translation did not come."""
    lines = []
    try:
        lines.append(f"Google: OK ({google_translate('Hello world.', src, dst)})")
    except RateLimited as e:
        lines.append(f"Google: refused ({e}) - it does not want to answer this computer for now")
    except Exception as e:
        lines.append(f"Google: failed ({type(e).__name__}: {e})")
    cfg = server_from_settings(settings) if settings else None
    if cfg:
        try:
            out = server_translate_group(cfg, ["Hello world."], src, dst)
            lines.append(f"Own server/Gemini: OK ({out[0]})" if out else "Own server/Gemini: answered, but not one line per text")
        except Exception as e:
            lines.append(f"Own server/Gemini: failed ({type(e).__name__}: {e})")
    elif settings and settings.get("server_kind") == "gemini":
        lines.append("Own server/Gemini: no API key entered")
    missing = missing_pairs(src, dst)
    lines.append(f"Better offline model ({better.NAME}): " + ("downloaded" if better.installed() else "not downloaded"))
    if missing:
        lines.append("Offline: language pack missing: " + ", ".join(f"{a}>{b}" for a, b in sorted(missing)))
    else:
        try:
            out = Translator()._argos_many(["Hello world."], src, dst)[0]
            lines.append(f"Offline: OK ({out})" if out else "Offline: answered nothing")
        except Exception as e:
            lines.append(f"Offline: failed ({type(e).__name__}: {e})")
    try:
        lines.append("Packs on disk: " + (", ".join(f"{a}>{b}" for a, b in sorted(packs.installed_pairs())) or "none")
                     + f"  ({packs.PACK_DIR})")
    except Exception as e:
        lines.append(f"Packs on disk: unreadable ({e})")
    return "\n".join(lines)
