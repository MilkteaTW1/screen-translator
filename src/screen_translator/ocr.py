"""Built-in OCR (offline, free): Windows OCR (languages = the OCR packs installed in Windows) or Apple Vision on macOS."""
import asyncio
import re
import sys
from dataclasses import dataclass

import numpy as np
from PySide6.QtCore import Qt  # Qt before winrt, or the process crashes
from PySide6.QtGui import QImage

if sys.platform == "win32":
    from winrt.windows.globalization import Language
    from winrt.windows.graphics.imaging import BitmapPixelFormat, SoftwareBitmap
    from winrt.windows.media.ocr import OcrEngine
    from winrt.windows.storage.streams import DataWriter
else:
    from . import ocr_mac

NO_SPACE_LANGS = {"ja", "zh", "th"}
LONE_WORDS = set("aAI&0123456789")  # one-character tokens that are real words or numbers
SENTENCE_END =(".", "!", "?", ":", ";", "。", "！", "？", "：")
KATAKANA_HYPHEN_RE =re.compile(r"(?<=[ァ-ヺ])[-‐‑–—―](?![A-Za-z0-9])")
UPSCALE = 2.0  # small text is read far better from an enlarged picture (eval/: 2.15% wrong characters down to 0.38%)
UPSCALE_MAX_SIDE = 3840  # ... but not past this size: a big screen has big text, and the time grows with the pixels
DARK_BELOW = 110  # mean brightness under which a picture is read inverted: OCR does better on dark text on light


@dataclass
class Line:
    x: float
    y: float
    w: float
    h: float
    text: str
    lh: float = 0  # height of one text line (a merged paragraph is taller than its lines)
    tag: str = ""  # OCR language this was read with, like en-US
    joiner: str = " "  # what goes between this language's words


def merge_paragraphs(lines, joiner=None, max_lines=12):
    """Join OCR lines that are stacked and left-aligned into one block, so a wrapped sentence is
    translated as a whole instead of fragment by fragment. Lines keep their own language's joiner unless one is given."""
    groups = []
    for l in sorted(lines, key=lambda l: (l.y, l.x)):
        for g in groups:
            last = g[-1]
            gap = l.y - (last.y + last.h)
            # Windows and panels have their own borders, so where a line wraps says little. The
            # sentence is what counts: a stacked line continues the previous one until that one
            # ends with . ! ? etc. Only a very short line (heading, button, menu item) breaks off.
            column = max([l.w] + [m.w for m in g])
            wraps = last.w >= 0.3 * column and not last.text.rstrip().endswith(SENTENCE_END)
            if (wraps and l.tag == last.tag and len(g) < max_lines and -0.3 * last.h <= gap <= 0.55 * last.h
                    and abs(l.x - last.x) <= 1.5 * last.h and 0.7 <= l.h / last.h <= 1.4):
                g.append(l)
                break
        else:
            groups.append([l])
    merged = []
    for g in groups:
        x0, y0 = min(l.x for l in g), min(l.y for l in g)
        x1, y1 = max(l.x + l.w for l in g), max(l.y + l.h for l in g)
        glue = g[0].joiner if joiner is None else joiner
        merged.append(Line(x0, y0, x1 - x0, y1 - y0, glue.join(l.text for l in g), g[0].h, g[0].tag, glue))
    return merged


def prepare(bgra, w, h):
    """The picture the OCR reads: (bytes, width, height, scale). Dark pictures are inverted and small ones enlarged."""
    a = np.frombuffer(bgra, np.uint8).reshape(h, w, 4)
    if a[::8, ::8, :3].mean() < DARK_BELOW:
        a = a.copy()
        a[:, :, :3] = 255 - a[:, :, :3]
    scale = min(UPSCALE, UPSCALE_MAX_SIDE / max(w, h))
    if scale < 1.2:
        return a.tobytes(), w, h, 1.0
    width, height = round(w * scale), round(h * scale)
    data = a.tobytes()  # QImage only borrows it
    big = QImage(data, w, h, w * 4, QImage.Format_RGB32).scaled(width, height, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
    return bytes(big.constBits())[:width * height * 4], width, height, width / w


def available_languages():
    """[(tag, display_name)] of the OCR languages: the packs installed in Windows, or what Apple Vision reads."""
    if sys.platform != "win32":
        return ocr_mac.languages()
    return [(l.language_tag, l.display_name) for l in OcrEngine.available_recognizer_languages]


# Letters the OCR mixes up, giving words that do not exist: "vou" for "you". Only misreadings that are not words themselves.
CONFUSED_WORDS = {"vou": "you", "vour": "your", "vours": "yours", "vourself": "yourself", "tbe": "the", "tbat": "that",
                  "tbis": "this", "wbat": "what", "wben": "when", "wbich": "which", "bave": "have", "witb": "with"}
CONFUSED_RE = re.compile(r"\b(" + "|".join(CONFUSED_WORDS) + r")\b", re.IGNORECASE)


def fix_confusions(text, tag):
    """Corrects the few English words OCR keeps misreading (keeps capitals). Other languages are left alone."""
    if not tag.lower().startswith("en"):
        return text

    def fix(m):
        word, right = m.group(), CONFUSED_WORDS[m.group().lower()]
        return right.upper() if word.isupper() else right.capitalize() if word[0].isupper() else right
    return CONFUSED_RE.sub(fix, text)


class Recognizer:
    def __init__(self, tag):
        self.tag = tag
        if sys.platform == "win32":
            self.engine = OcrEngine.try_create_from_language(Language(tag))
            if self.engine is None:
                raise RuntimeError(f"OCR language not available: {tag}")
        self.joiner = "" if tag.split("-")[0].lower() in NO_SPACE_LANGS else " "

    async def _run(self, bgra, w, h):
        writer = DataWriter()
        writer.write_bytes(bgra)
        bitmap = SoftwareBitmap.create_copy_from_buffer(
            writer.detach_buffer(), BitmapPixelFormat.BGRA8, w, h
        )
        return await self.engine.recognize_async(bitmap)

    def recognize(self, bgra, w, h):
        return self.read_prepared(*prepare(bytes(bgra), w, h))

    def _read_mac(self, data, w, h, scale):
        lines = []
        for text, x, y, bw, bh in ocr_mac.read(data, w, h, self.tag):
            text = text.strip()
            if self.joiner:
                text = fix_confusions(text, self.tag)
            if text:
                lines.append(Line(x / scale, y / scale, bw / scale, bh / scale, text, 0, self.tag, self.joiner))
        return lines

    def read_prepared(self, data, w, h, scale):
        if sys.platform != "win32":
            return self._read_mac(data, w, h, scale)
        result = asyncio.run(self._run(data, w, h))
        lines = []
        for line in result.lines:
            words = list(line.words)
            if not words:
                continue
            rects = [wd.bounding_rect for wd in words]
            x0 = min(r.x for r in rects)
            y0 = min(r.y for r in rects)
            x1 = max(r.x + r.width for r in rects)
            y1 = max(r.y + r.height for r in rects)
            text = self.joiner.join(wd.text for wd in words)
            if self.joiner == "":  # CJK: OCR often reads the katakana long-vowel mark ー as an ASCII hyphen
                text = KATAKANA_HYPHEN_RE.sub("ー", text)
            else:  # icons next to text (a chevron, a bullet) come out as stray one-letter "words"
                text = " ".join(t for t in text.split() if len(t) > 1 or t in LONE_WORDS)
                text = fix_confusions(text, self.tag)
            lines.append(Line(x0 / scale, y0 / scale, (x1 - x0) / scale, (y1 - y0) / scale, text, 0, self.tag, self.joiner))
        return lines


def _overlap(a, b):
    ix = max(0, min(a.x + a.w, b.x + b.w) - max(a.x, b.x))
    iy = max(0, min(a.y + a.h, b.y + b.h) - max(a.y, b.y))
    smaller = min(a.w * a.h, b.w * b.h)
    return ix * iy / smaller if smaller else 0.0


def script_fit(text, tag):
    """How much of `text` is written in the script of OCR language `tag` (0..1), and how much that is in letters."""
    from .translator import KANA_RE, SCRIPT_RE
    base = tag.split("-")[0].lower()
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return 0.0, 0
    pattern = SCRIPT_RE.get(base)
    hits = sum(1 for c in letters if (pattern.match(c) if pattern else c.isascii()))
    fit = hits / len(letters)
    if base == "ja" and len(KANA_RE.findall(text)) < 2:
        fit *= 0.3  # kanji with no kana is Chinese
    return fit, len(letters)


class AutoRecognizer:
    """Reads the screen with every installed OCR language and keeps, for each place, the reading that is in its own
    language's script: English text from the English engine, Japanese from the Japanese one, and so on."""
    tag = "auto"
    joiner = " "

    def __init__(self, recognizers):
        self.recognizers = recognizers

    def recognize(self, bgra, w, h):
        scored = []
        prepared = prepare(bytes(bgra), w, h)  # once: every language reads the same picture
        for r in self.recognizers:
            for line in r.read_prepared(*prepared):
                fit, count = script_fit(line.text, line.tag)
                scored.append((fit >= 0.7, fit * count, line))
        scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
        kept = []
        for _ok, _score, line in scored:
            if all(_overlap(line, k) < 0.4 for k in kept):
                kept.append(line)
        return sorted(kept, key=lambda l: (l.y, l.x))


def make_recognizer(tag):
    """The OCR for a chosen language, or for 'auto' one that reads with all installed languages."""
    if tag == "auto":
        chosen = {}
        tags = [t for t, _n in available_languages()]
        if sys.platform != "win32":  # Vision knows about 30 languages: reading with all of them would be slow
            tags = [t for t in ocr_mac.AUTO_PREFERRED if t in tags] or tags[:3]
        for t in tags:  # one engine per language: not both en-US and en-GB
            base = t.split("-")[0].lower()
            if base not in chosen or t == "en-US":
                chosen[base] = t
        return AutoRecognizer([Recognizer(t) for t in chosen.values()])
    return Recognizer(tag)
