"""Windows built-in OCR (offline, free). Languages = the OCR packs installed in Windows."""
import asyncio
import re
from dataclasses import dataclass

from winrt.windows.globalization import Language
from winrt.windows.graphics.imaging import BitmapPixelFormat, SoftwareBitmap
from winrt.windows.media.ocr import OcrEngine
from winrt.windows.storage.streams import DataWriter

NO_SPACE_LANGS = {"ja", "zh", "th"}
LONE_WORDS = set("aAI&0123456789")  # one-character tokens that are real words or numbers
SENTENCE_END =(".", "!", "?", ":", ";", "。", "！", "？", "：")
KATAKANA_HYPHEN_RE =re.compile(r"(?<=[ァ-ヺ])[-‐‑–—―](?![A-Za-z0-9])")


@dataclass
class Line:
    x: float
    y: float
    w: float
    h: float
    text: str
    lh: float = 0  # height of one text line (a merged paragraph is taller than its lines)


def merge_paragraphs(lines, joiner=" ", max_lines=12):
    """Join OCR lines that are stacked and left-aligned into one block, so a wrapped sentence is
    translated as a whole instead of fragment by fragment."""
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
            if (wraps and len(g) < max_lines and -0.3 * last.h <= gap <= 0.55 * last.h
                    and abs(l.x - last.x) <= 1.5 * last.h and 0.7 <= l.h / last.h <= 1.4):
                g.append(l)
                break
        else:
            groups.append([l])
    merged = []
    for g in groups:
        x0, y0 = min(l.x for l in g), min(l.y for l in g)
        x1, y1 = max(l.x + l.w for l in g), max(l.y + l.h for l in g)
        merged.append(Line(x0, y0, x1 - x0, y1 - y0, joiner.join(l.text for l in g), g[0].h))
    return merged


def available_languages():
    """[(tag, display_name)] of OCR languages installed in Windows."""
    return [(l.language_tag, l.display_name) for l in OcrEngine.available_recognizer_languages]


class Recognizer:
    def __init__(self, tag):
        self.tag = tag
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
        result = asyncio.run(self._run(bytes(bgra), w, h))
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
            lines.append(Line(x0, y0, x1 - x0, y1 - y0, text))
        return lines
