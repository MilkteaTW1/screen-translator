"""Screen Translator: pick source/target language, translate on-screen text in place, keep proper nouns."""
# The translation engine must be loaded before the WinRT OCR modules (imported below, via `ocr`): when it is first
# loaded after OCR has run, the process crashes. That happens to anyone who downloads a language pack while the app runs.
import ctranslate2  # noqa: F401
import sentencepiece  # noqa: F401
import ctypes
import winreg
import difflib
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import mss
import numpy as np
from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QFileDialog, QComboBox, QDoubleSpinBox, QFormLayout, QGroupBox, QHBoxLayout, QLabel,
    QLineEdit, QMenu, QMessageBox, QPlainTextEdit, QPushButton, QSystemTrayIcon, QTabWidget, QVBoxLayout, QWidget,
)

from . import ocr, tracking
from .overlay import CaptionOverlay, CoverChip, Overlay
from .speech import MODELS, SpeechWorker, download_model, ensure_streams, find_model, import_model
from . import __version__, i18n, packs, updater
from .i18n import t
from .translator import (
    LANGUAGES, Translator, argos_code, install_pack, looks_like_source, missing_pairs, needed_pairs, ocr_tag_to_code,
)

SETTINGS_PATH = Path(os.environ.get("APPDATA", Path.home())) / "ScreenTranslator" / "settings.json"
DEFAULTS = {
    "source": "en-US", "target": "zh-TW", "interval": 1.0,
    "auto_proper": True, "keep_katakana": False, "glossary": "",
    "hide_from_capture": True, "skip_names": True,
    "autostart": False, "start_on_launch": False,
    "speech_enabled": False, "speech_source": "system", "speech_model": "base", "speech_lang": "auto",
    "use_google": True,
    "ui_language": "",  # interface language; empty = the one Windows is set to
}
MAX_BLOCKS = 40  # most text blocks translated per screen pass
BATCH = 8  # blocks translated together (one engine call) and shown together
SCROLL_SETTLE = 0.35  # seconds the page must stay still after scrolling before it is read again
SCROLL_READ_EVERY = 0.8  # seconds between reads while the page keeps scrolling
SCROLL_LEAD = 0.06  # seconds: while scrolling, boxes are drawn this far ahead (a screenshot is already late when drawn)
POLL = 0.08  # seconds between cheap looks at the screen (grab + compare is ~30 ms); a scan starts when it changed
CONFIRM_GAP = 0.1  # seconds before the second look that confirms newly seen text


def scan_due(changed, dirty, since_last, interval):
    """Whether to OCR now. A new or changed screen is scanned at once if it has been quiet for `interval`
    (that setting only limits how often a constantly changing screen, like a video, is scanned);
    text waiting for its confirming second look gets a short fixed gap."""
    return (changed or dirty) and since_last >= (CONFIRM_GAP if dirty else interval)


RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


def set_autostart(on):
    """Start with Windows (current user, no admin rights): a value under the Run registry key."""
    exe = sys.executable if getattr(sys, "frozen", False) else f'"{sys.executable}" -m screen_translator'
    cmd = f'"{exe}" --minimized' if getattr(sys, "frozen", False) else f"{exe} --minimized"
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
        if on:
            winreg.SetValueEx(k, "ScreenTranslator", 0, winreg.REG_SZ, cmd)
        else:
            try:
                winreg.DeleteValue(k, "ScreenTranslator")
            except FileNotFoundError:
                pass


def lower_priority():
    """Run below normal priority so translating never competes with what the user is doing."""
    try:
        ctypes.windll.kernel32.SetPriorityClass(ctypes.windll.kernel32.GetCurrentProcess(), 0x4000)
    except Exception:
        pass


def _iou(a, b):
    """Overlap of two (x, y, w, h) boxes as a share of their union."""
    ix = max(0, min(a[0] + a[2], b[0] + b[2]) - max(a[0], b[0]))
    iy = max(0, min(a[1] + a[3], b[1] + b[3]) - max(a[1], b[1]))
    inter = ix * iy
    union = a[2] * a[3] + b[2] * b[3] - inter
    return inter / union if union else 0.0


def load_settings():
    try:
        return {**DEFAULTS, **json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))}
    except Exception:
        return dict(DEFAULTS)


def _visible(track):
    """The translation to draw for a followed block: only once it has been seen twice and translated. While its
    text is being translated again (the paragraph grew as it scrolled into view) the old translation stays."""
    if track["seen"] < 2:
        return None
    return track["translation"] if track["done"] else track.get("stale")


def _grows(old, new):
    """True when one text is the other with more (or less) of the same paragraph: a block cut off by the screen
    edge shows more lines as it scrolls in."""
    short, long_ = sorted((old, new), key=len)
    return len(short) >= 12 and (short in long_ or long_.startswith(short[:max(12, int(len(short) * 0.7))]))


class Worker(QObject):
    results = Signal(list)
    status = Signal(str)
    background = Signal(tuple)

    def __init__(self, langs):
        super().__init__()
        self.langs = langs  # display name -> language code
        self.settings = load_settings()
        self.translator = Translator()
        self._use_engine(self.settings)
        self.running = False
        self.dirty = True
        self.thread = None
        self.background_translation = False  # translate on a thread of its own, so scanning never waits for the network
        self._jobs = []  # batches of tracks waiting to be translated; the newest is done first
        self._jobs_lock = threading.Lock()
        self._jobs_ready = threading.Event()
        self.shown = set()  # translations currently on screen, whitespace-stripped
        self.tracks = []  # text blocks followed from scan to scan: position, text, translation, times seen
        self._others = []  # (x, y, w, h, line height) of lines we do not translate: the overlay keeps clear of them
        self.overlay_rects = lambda: []  # set by main(): the boxes the overlay has drawn, in screen pixels
        self.mask_own_overlay = True
        self._recognizer, self._prev, self._prev_keep, self._prev_gray = None, None, None, None
        self._prev_gray_boxes = []
        self._last_scan = 0.0
        self._boxes = []  # our own boxes in the picture being scanned
        self.static = False  # the screen barely changed since the previous scan
        self.scrolling_until = 0.0  # no OCR while the page moves; it is read again once it stops
        self.velocity = (0.0, 0.0)  # pixels per second the page is scrolling
        self._last_follow = 0.0
        self._settled_at = 0.0
        self.origin = (0, 0)  # top-left of the scanned area, added back so the overlay draws in screen coordinates

    def configure(self, settings):
        self.settings = settings
        self._use_engine(settings)
        self.tracks = []
        with self._jobs_lock:
            self._jobs.clear()
        self.translator.clear()
        self.dirty = True

    def _use_engine(self, s):
        self.translator.google = bool(s.get("use_google", True))

    def start(self):
        if self.running:
            return
        self.running = True
        self.dirty = True
        self.background_translation = True
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()
        threading.Thread(target=self._translate_loop, daemon=True).start()

    def stop(self):
        self.running = False
        self._jobs_ready.set()
        self.results.emit([])

    def _loop(self):
        with mss.mss() as sct:
            mon = sct.monitors[1]
            while self.running:
                s = self.settings
                try:
                    region = s.get("region")  # [left, top, width, height]: translate only this part of the screen
                    self.origin = (region[0], region[1]) if region else (0, 0)
                    shot = sct.grab(dict(left=region[0], top=region[1], width=region[2], height=region[3])
                                    if region else mon)
                    self._step(shot, time.monotonic())
                except Exception as e:  # keep the loop alive; show the problem in the UI
                    self.status.emit(t("status_error", err=e))
                    time.sleep(1.0)  # do not retry a failing step 12 times a second
                time.sleep(POLL)

    def _own_boxes(self):
        """Translation boxes the overlay has drawn, in the captured picture's pixels: they are only in the picture
        when screenshots are allowed to include translations (otherwise Windows leaves them out)."""
        if not self.mask_own_overlay or self.settings["hide_from_capture"]:
            return []
        ox, oy = self.origin
        return [(x0 - ox, y0 - oy, x1 - ox, y1 - oy) for x0, y0, x1, y1 in self.overlay_rects()]

    @staticmethod
    def _keep_mask(shape, boxes, step=8, margin=8):
        """Grid (one cell per `step` px) that is False where one of our own boxes is drawn."""
        keep = np.ones((len(range(0, shape[0], step)), len(range(0, shape[1], step))), bool)
        for x0, y0, x1, y1 in boxes:
            keep[max(0, int(y0 - margin) // step):max(0, int(y1 + margin) // step + 1),
                 max(0, int(x0 - margin) // step):max(0, int(x1 + margin) // step + 1)] = False
        return keep

    @staticmethod
    def _cover_share(box, boxes):
        """How much of box (x, y, w, h) our own boxes cover, 0..1."""
        x, y, w, h = box
        if w <= 0 or h <= 0:
            return 0.0
        area = 0.0
        for x0, y0, x1, y1 in boxes:
            area += max(0.0, min(x + w, x1) - max(x, x0)) * max(0.0, min(y + h, y1) - max(y, y0))
        return min(1.0, area / (w * h))

    def _step(self, shot, now):
        """One look at the screen: follow a scroll, and OCR + translate when something new may be there."""
        s = self.settings
        if self._recognizer is None or self._recognizer.tag != s["source"]:
            self._recognizer = ocr.make_recognizer(s["source"])
        arr = np.frombuffer(shot.bgra, np.uint8).reshape(shot.height, shot.width, 4)
        boxes = self._own_boxes()
        keep = self._keep_mask(arr.shape, boxes)
        for t in self.tracks:
            t["followed"] = False
        small = arr[::8, ::8, :3].astype(np.int16)
        prev = self._prev
        if prev is None or small.shape != prev.shape:
            diff = None
        else:  # our own translation boxes (drawn now or at the last scan) are not "the screen changing"
            both = keep & self._prev_keep
            diff = float(np.abs(small - prev)[both].mean()) if both.any() else 0.0
        self.static = diff is not None and diff < 2.0  # barely changed: not scrolling or playing video
        changed = diff is None or diff > 0.6
        green = arr[:, :, 1]  # one channel is enough to follow shifting text
        scrolled = False
        if changed and self.tracks and self._prev_gray is not None and not self.static:
            shift = self._follow_scroll(self._prev_gray, green, boxes, self._prev_gray_boxes)
            scrolled = shift not in (None, (0, 0))  # (0, 0): nothing measurable moved
            if shift != (0, 0):  # (0, 0): too little to measure yet
                self._prev_gray, self._prev_gray_boxes = green, boxes
            if shift is None:  # the page changed: what we cover may be gone, and we cannot see under it
                self.tracks = [t for t in self.tracks if not t.get("covered")]
        else:
            self._prev_gray, self._prev_gray_boxes = green, boxes
        # On a frame where the picture has just scrolled, our own boxes still sit where the text was a moment ago
        # and would cover the wrong words: wait for the next frame (a long scroll is still read once a second).
        # While the page moves the translations go with it (drawn a little ahead, since every screenshot is already
        # late by the time it is drawn); the page is read again once it has stopped for a moment.
        if scrolled:
            dt = now - self._last_follow
            if 0 < dt < 0.5:
                vx, vy = shift[0] / dt, shift[1] / dt
                self.velocity = (0.5 * self.velocity[0] + 0.5 * vx, 0.5 * self.velocity[1] + 0.5 * vy)
            else:
                self.velocity = (0.0, 0.0)
            self._last_follow = now
            self.scrolling_until = now + SCROLL_SETTLE
            # the overlay looks for empty space on the current picture, not on the one from before the scroll
            gray = (arr[::4, ::4, :3].astype(np.int32) * (114, 587, 299)).sum(axis=2) // 1000  # B, G, R
            self.background.emit((gray.astype(np.int16), self.origin))
            self.results.emit(self._snapshot(now))
        elif self.scrolling_until and now >= self.scrolling_until:
            self.scrolling_until = 0.0
            self.velocity = (0.0, 0.0)
            self.dirty = True  # read the settled page once
            self.results.emit(self._snapshot(now))
            self._settled_at = now
        # ... but only once our boxes are back on their text: the picture just taken still has them drawn ahead,
        # over other lines, and reading it would give fragments that look like new text.
        # A long scroll is still read now and then, so new text coming into view gets translated on the way.
        wait = (now < self.scrolling_until and now - self._last_scan < SCROLL_READ_EVERY) or now - self._settled_at < 0.2
        if scan_due(changed, self.dirty, now - self._last_scan, s["interval"]) and not wait:
            self._prev, self._prev_keep, self.dirty = small, keep, False
            gray = (arr[::4, ::4, :3].astype(np.int32) * (114, 587, 299)).sum(axis=2) // 1000  # B, G, R
            self.background.emit((gray.astype(np.int16), self.origin))
            self._boxes = boxes
            self.results.emit(self._process(self._recognizer, shot, s))
            self.status.emit(self._status_text())
            # Text seen only once is not shown yet: look again soon to confirm it.
            self.dirty = self.dirty or any(t["seen"] < 2 for t in self.tracks)
            self._last_scan = time.monotonic()

    def _follow_scroll(self, before, now, boxes=(), before_boxes=()):
        """The picture scrolled: move the translations with it right away (no OCR, no new translation), and drop
        the ones that left the screen. Returns what tracking.follow returned."""
        for t in self.tracks:  # a block hidden under our own box cannot show its own pixels moving
            t["covered"] = bool(before_boxes) and _visible(t) is not None and self._cover_share(
                (t["x"], t["y"], t["w"], t["h"]), before_boxes) >= 0.6
        shift = tracking.follow(self.tracks, before, now, ignore=[*boxes, *before_boxes])
        if not shift or shift == (0, 0):
            return shift
        dx, dy = shift
        height, width = now.shape
        self._others = [(x + dx, y + dy, w, h, lh) for x, y, w, h, lh in self._others]
        self.tracks = [t for t in self.tracks if t["x"] + t["w"] > 0 and t["x"] < width
                       and t["y"] + t["h"] > 0 and t["y"] < height]
        return shift

    def _snapshot(self, now=None):
        """What the overlay draws. Lines we don't translate are included (text None) so it avoids covering them.
        While the page scrolls, everything is drawn a little ahead along the scroll."""
        ox, oy = self.origin
        if (time.monotonic() if now is None else now) < self.scrolling_until:
            ox += int(round(self.velocity[0] * SCROLL_LEAD))
            oy += int(round(self.velocity[1] * SCROLL_LEAD))
        items = [(x + ox, y + oy, w, h, None, lh) for x, y, w, h, lh in self._others]
        items += [(t["x"] + ox, t["y"] + oy, t["w"], t["h"], _visible(t), t["lh"]) for t in self.tracks]
        return items

    def _status_text(self):
        t = self.translator
        if t.missing_packs:
            need = ", ".join(f"{a}→{b}" for a, b in sorted(t.missing_packs))
            return i18n.t("status_packs_needed", names=need)
        engine = t.engine or ("google" if t.google else "offline")  # nothing translated yet: the one that will be tried
        return i18n.t("status_running_google" if engine == "google" else "status_running_offline")

    def _process(self, recognizer, shot, s):
        glossary = [t.strip() for t in s["glossary"].splitlines() if t.strip()]
        boxes = self._boxes
        everything = [l for l in recognizer.recognize(shot.bgra, shot.width, shot.height)
                      if self._cover_share((l.x, l.y, l.w, l.h), boxes) < 0.5]  # not our own translations
        supported = set(self.langs.values())
        target = s["target"]

        code_of = lambda l: ocr_tag_to_code(l.tag or s["source"], supported)

        # A line cut off by the top or bottom edge reads as nonsense fragments: wait until it is fully in view.
        # (At the edge, so a paragraph that runs off the screen loses only its first or last line, never a middle one.)
        lines = [l for l in everything if l.y > 3 and l.y + l.h < shot.height - 3 and not self._is_own_output(l.text)]
        # Merge first, judge afterwards: a name, hashtag or code in the middle of a sentence used to fail the check
        # for its own line, which left a hole in the paragraph and a mistranslated sentence. Judged as a whole it passes.
        merged = ocr.merge_paragraphs(lines)  # translate whole paragraphs, not fragments

        def wanted(b):  # in the source language (each block says which OCR language read it), and not already the target
            return (looks_like_source(b.text, b.tag or s["source"], b.w, b.lh or b.h, s["skip_names"])
                    and argos_code(code_of(b)) != argos_code(target))

        blocks = [b for b in merged if wanted(b)]
        blocks.sort(key=lambda b: (b.y, b.x))
        kept_ids = {id(b) for b in blocks}
        edge = [l for l in everything if l not in lines]
        self._others = [(b.x, b.y, b.w, b.h, b.h) for b in merged if id(b) not in kept_ids] +                        [(l.x, l.y, l.w, l.h, l.h) for l in edge]

        # OCR reads the same text a little differently on every scan (a misread letter, a different
        # line break, a pass where it is missed altogether). Follow each text block from scan to scan
        # as a "track" so that what is on screen stays steady:
        #  - a block that matches an earlier one keeps its translation and position,
        #  - a new block is only shown once it has been seen twice (one-scan noise never appears),
        #  - a shown block that is missed once on a still screen stays (OCR dropout).
        fresh, used = [], set()
        for b in blocks:
            t = self._match_track(b, used, boxes)
            part = None if t else self._part_of(b)
            if part is not None:  # a piece of a block we already show (our own box hid the rest): not new text
                if id(part) not in used:
                    used.add(id(part))
                    part["missed"] = 0
                    fresh.append(part)
                continue
            if t:
                used.add(id(t))
                t["seen"] += 1
                t["missed"] = 0
                if t["text"] != b.text and difflib.SequenceMatcher(None, b.text, t["text"]).ratio() < 0.8:
                    t["stale"] = t["translation"] or t.get("stale")  # keep showing it until the new one is ready
                    t.update(text=b.text, translation=None, done=False)
                if not self._same_place(t, b):  # it really moved (scrolling): follow it
                    t.update(x=b.x, y=b.y, w=b.w, h=b.h, lh=b.lh)
            else:
                t = {"x": b.x, "y": b.y, "w": b.w, "h": b.h, "lh": b.lh, "text": b.text, "tag": b.tag or s["source"],
                     "translation": None, "done": False, "seen": 1, "missed": 0}
            fresh.append(t)
        carried = []
        for t in self.tracks:
            if id(t) not in used:
                if _visible(t) is not None and self._cover_share((t["x"], t["y"], t["w"], t["h"]), boxes) >= 0.6:
                    carried.append(t)  # hidden under our own box: the scan cannot see it, but it is still there
                    continue
                if t.get("followed"):
                    carried.append(t)  # its own pixels were just seen moving with the scroll: it is still there
                    continue
                t["missed"] += 1
                if self.static and t["seen"] >= 2 and t["missed"] <= 1:
                    carried.append(t)
        # a carried block that a fresh one now sits on top of is the same text read again: one box is enough
        carried = [t for t in carried if not any(
            _iou((t["x"], t["y"], t["w"], t["h"]), (f["x"], f["y"], f["w"], f["h"])) > 0.5 for f in fresh)]
        self.tracks = fresh + carried

        for t in fresh:  # already translated earlier: straight from the cache
            key = (t["text"], ocr_tag_to_code(t["tag"], supported), target)
            if not t["done"] and key in self.translator.cache:
                t["translation"], t["done"] = self.translator.cache[key], True
                if t["translation"]:  # text we have read and translated before (it just moved): no need to confirm it
                    t["seen"] = max(t["seen"], 2)

        # Translate top to bottom in small batches and show each batch as it finishes, so a
        # screen full of text fills in progressively instead of freezing until everything is done.
        self._update_shown()
        todo = [t for t in fresh if not t["done"] and not t.get("queued")][:MAX_BLOCKS]
        jobs = [todo[i:i + BATCH] for i in range(0, len(todo), BATCH)]
        if self.background_translation:
            for batch in jobs:
                for t in batch:
                    t["queued"] = True
            with self._jobs_lock:
                self._jobs.extend(reversed(jobs))  # the job taken first is the topmost batch
            self._jobs_ready.set()
        else:
            for i, batch in enumerate(jobs):
                self._translate_batch(batch, glossary, s)
                if i + 1 < len(jobs):
                    self.results.emit(self._snapshot())
                    if not self.running or self.dirty:  # the user changed something: restart with fresh settings
                        break
        return self._snapshot()

    def _update_shown(self):
        self.shown = {"".join(v.split()) for v in map(_visible, self.tracks) if v}

    def _translate_batch(self, batch, glossary, s):
        supported = set(self.langs.values())
        for tag in dict.fromkeys(t["tag"] for t in batch):  # one engine call per source language
            same = [t for t in batch if t["tag"] == tag]
            texts = [t["text"] for t in same]
            args = (ocr_tag_to_code(tag, supported), s["target"], tag, glossary, s["auto_proper"], s["keep_katakana"])
            for t, text, out in zip(same, texts, self.translator.translate_many(texts, *args)):
                if t["text"] == text:  # the block was read differently meanwhile: this answer is for old text
                    t["translation"], t["done"], t["queued"] = out, True, False
                else:
                    t["queued"] = False
        self._update_shown()

    def _translate_loop(self):
        while self.running:
            self._jobs_ready.wait(1.0)
            while self.running:
                with self._jobs_lock:
                    live = {id(t) for t in self.tracks}
                    job = None
                    while self._jobs and job is None:
                        batch = self._jobs.pop()
                        job = [t for t in batch if id(t) in live]  # blocks that scrolled away need no translation
                        for t in batch:
                            if id(t) not in live:
                                t["queued"] = False
                        job = job or None
                    if not self._jobs:
                        self._jobs_ready.clear()
                if job is None:
                    break
                s = self.settings
                glossary = [x.strip() for x in s["glossary"].splitlines() if x.strip()]
                try:
                    self._translate_batch(job, glossary, s)
                except Exception as e:
                    for t in job:
                        t["queued"] = False
                    self.status.emit(i18n.t("status_error", err=e))
                self.results.emit(self._snapshot())
                self.status.emit(self._status_text())  # the engine is known once something is translated
                self.dirty = self.dirty or any(t["seen"] < 2 for t in self.tracks)

    def _match_track(self, block, used, boxes=()):
        """The earlier text block this one most likely is: overlapping area and nearly the same text (less alike is
        fine where our own boxes cover part of it: the scan then reads only part of the text)."""
        best, best_iou = None, 0.5
        for t in self.tracks:
            if id(t) in used:
                continue
            iou = _iou((block.x, block.y, block.w, block.h), (t["x"], t["y"], t["w"], t["h"]))
            need = 0.5 if self._cover_share((t["x"], t["y"], t["w"], t["h"]), boxes) >= 0.15 else 0.8
            if iou > best_iou and (difflib.SequenceMatcher(None, block.text, t["text"]).ratio() >= need
                                   or _grows(t["text"], block.text)):
                best, best_iou = t, iou
        return best

    def _part_of(self, block):
        """The shown block this one is only a piece of (same lines, text contained in it), if any."""
        piece = "".join(block.text.split())
        if len(piece) < 4:
            return None
        for t in self.tracks:
            if (_visible(t) is not None and piece in "".join(t["text"].split())
                    and block.y < t["y"] + t["h"] and t["y"] < block.y + block.h):
                return t
        return None

    @staticmethod
    def _same_place(track, b):
        return (abs(track["x"] - b.x) <= 8 and abs(track["y"] - b.y) <= 8
                and abs(track["w"] - b.w) <= 12 and abs(track["h"] - b.h) <= 12)

    def _is_own_output(self, text):
        """True if OCR picked up one of our own translations (guards against re-translating them)."""
        norm = "".join(text.split())
        return any(difflib.SequenceMatcher(None, norm, s).ratio() >= 0.7 for s in self.shown)


class Panel(QWidget):
    pack_status = Signal(str)
    pack_finished = Signal()
    speech_model_done = Signal(bool)
    update_found = Signal(str, str)
    update_ready = Signal(str)
    language_changed = Signal()

    def __init__(self, worker, overlay, langs, speech=None, captions=None):
        super().__init__()
        self.worker, self.overlay = worker, overlay
        self.speech, self.captions = speech, captions
        self.langs = langs
        self.downloading = False
        self.setWindowTitle("Screen Translator")
        self.setMinimumWidth(420)
        s = worker.settings
        self.ui_language = s["ui_language"]
        self._texts = []  # (setter, key) pairs, re-applied when the interface language changes

        self.source = QComboBox()
        installed = ocr.available_languages()
        if installed:
            self.source.addItem("", "auto")
        for tag, name in installed:
            self.source.addItem(f"{name} ({tag})", tag)
        self._select(self.source, s["source"])
        self.target = QComboBox()
        for name, code in sorted(langs.items()):
            self.target.addItem(name.title(), code)
        self._select(self.target, s["target"])
        self.interval = QDoubleSpinBox()
        self.interval.setRange(0.0, 10)
        self.interval.setDecimals(2)
        self.interval.setSingleStep(0.05)
        self.interval.setSuffix(" s")
        self.interval.setValue(s["interval"])
        self.auto = self._check("auto_proper", s["auto_proper"])
        self.kata = self._check("keep_katakana", s["keep_katakana"])
        self.hide_capture = self._check("hide_capture", s["hide_from_capture"])
        self.skip_names = self._check("skip_names", s["skip_names"])
        self.autostart = self._check("autostart", s["autostart"])
        self.start_on_launch = self._check("start_on_launch", s["start_on_launch"])
        self.google = self._check("google_enable", s["use_google"])
        self.speech_enabled = self._check("speech_enable", s["speech_enabled"])
        self.speech_source = QComboBox()
        self.speech_source.addItem("", "system")
        self.speech_source.addItem("", "mic")
        self.speech_model = QComboBox()
        for name in MODELS:
            self.speech_model.addItem(name, name)
        self.speech_lang = QComboBox()
        self.speech_lang.addItem("", "auto")
        seen = set()
        for name, code in sorted(langs.items()):
            base = code.split("-")[0]
            if base not in seen:
                seen.add(base)
                self.speech_lang.addItem(name.title(), base)
        self._select(self.speech_source, s["speech_source"])
        self._select(self.speech_model, s["speech_model"])
        self._select(self.speech_lang, s["speech_lang"])
        self.speech_state = QLabel("")
        self.glossary = QPlainTextEdit(s["glossary"])
        self.toggle = QPushButton()  # screen translation on/off
        self.toggle.clicked.connect(self.on_toggle)
        self.speech_toggle = QPushButton()  # speech translation on/off: independent of the screen one
        self.speech_toggle.clicked.connect(lambda: self.speech_enabled.setChecked(not self.speech_enabled.isChecked()))
        self.state = QLabel()
        self.update_button = QPushButton()
        self._text(self.update_button.setText, "check_updates")
        self.update_button.clicked.connect(lambda: self.check_for_updates(quiet=False))
        self.version_label = QLabel()
        self._text(self.version_label.setText, "version_label", version=__version__)
        self.language_button = QPushButton()
        self.language_button.setMenu(QMenu(self.language_button))
        self.language_button.menu().aboutToShow.connect(self._fill_language_menu)

        # Settings are sorted into tabs by what they are for; Start/Stop and the status stay visible below them.
        self.tabs = QTabWidget()
        self.tabs.setUsesScrollButtons(False)
        translate = QWidget()
        form = QFormLayout()
        self._row(form, "screen_language", self.source)
        self._row(form, "translate_to", self.target)
        self._row(form, "refresh_interval", self.interval)
        lay = QVBoxLayout(translate)
        lay.addLayout(form)
        lay.addWidget(self.hide_capture)
        lay.addWidget(self.skip_names)
        lay.addStretch(1)
        self._tab(translate, "tab_translate")

        speech_tab = QWidget()
        lay = QVBoxLayout(speech_tab)
        lay.addWidget(self.speech_enabled)
        speech_form = QFormLayout()
        self._row(speech_form, "audio_from", self.speech_source)
        self._row(speech_form, "speech_language", self.speech_lang)
        self._row(speech_form, "speech_model", self.speech_model)
        lay.addLayout(speech_form)
        lay.addStretch(1)
        self._tab(speech_tab, "tab_speech")

        quality = QWidget()
        lay = QVBoxLayout(quality)
        names = QGroupBox()
        self._text(names.setTitle, "group_names")
        box = QVBoxLayout(names)
        box.addWidget(self.auto)
        box.addWidget(self.kata)
        label = QLabel()
        self._text(label.setText, "glossary_label")
        box.addWidget(label)
        box.addWidget(self.glossary)
        lay.addWidget(names)
        engine = QGroupBox()
        self._text(engine.setTitle, "group_engine")
        box = QVBoxLayout(engine)
        box.addWidget(self.google)
        lay.addWidget(engine)
        lay.addStretch(1)
        self._tab(quality, "tab_quality")

        general = QWidget()
        lay = QVBoxLayout(general)
        startup = QGroupBox()
        self._text(startup.setTitle, "group_startup")
        box = QVBoxLayout(startup)
        box.addWidget(self.autostart)
        box.addWidget(self.start_on_launch)
        lay.addWidget(startup)
        app_box = QGroupBox()
        self._text(app_box.setTitle, "group_app")
        box = QVBoxLayout(app_box)
        box.addWidget(self.update_button)
        box.addWidget(self.version_label)
        lay.addWidget(app_box)
        lay.addStretch(1)
        self._tab(general, "tab_general")

        top = QHBoxLayout()
        top.addStretch(1)
        top.addWidget(self.language_button)
        main = QVBoxLayout(self)
        main.addLayout(top)
        main.addWidget(self.tabs)
        buttons = QHBoxLayout()
        buttons.addWidget(self.toggle)
        buttons.addWidget(self.speech_toggle)
        main.addLayout(buttons)
        main.addWidget(self.state)
        main.addWidget(self.speech_state)

        for w in (self.source, self.target):
            w.currentIndexChanged.connect(self.apply)
            w.currentIndexChanged.connect(self.ensure_packs)
        self.pack_status.connect(self.state.setText)
        self.pack_finished.connect(self._packs_ready)
        self.update_found.connect(self._offer_update)
        self.update_ready.connect(self._run_installer)
        self.interval.valueChanged.connect(self.apply)
        self.hide_capture.toggled.connect(self.apply)
        self.skip_names.toggled.connect(self.apply)
        self.auto.toggled.connect(self.apply)
        self.kata.toggled.connect(self.apply)
        self.glossary.textChanged.connect(self.apply)
        self.google.toggled.connect(self.apply)
        self.autostart.toggled.connect(self.apply)
        self.start_on_launch.toggled.connect(self.apply)
        worker.status.connect(self.state.setText)
        worker.results.connect(overlay.set_items)
        self.speech_enabled.toggled.connect(self.apply)
        self.speech_enabled.toggled.connect(self.on_speech_toggle)
        self.speech_enabled.toggled.connect(self._show_toggles)
        for w in (self.speech_source, self.speech_model):
            w.currentIndexChanged.connect(self.apply)
            w.currentIndexChanged.connect(self._restart_speech)
        self.speech_lang.currentIndexChanged.connect(self.apply)
        self.speech_model_done.connect(self._speech_model_done)
        if speech is not None:
            speech.status.connect(self.speech_state.setText)
            speech.line.connect(captions.add)
            speech.partial.connect(captions.set_live)

        self.retranslate()
        self.state.setText(t("state_stopped"))
        if not installed:
            self.state.setText(t("no_ocr"))
            self.toggle.setEnabled(False)

    # -- interface language -------------------------------------------------------------------------------------
    def _text(self, setter, key, **values):
        """Show t(key) through setter now, and again whenever the interface language changes."""
        self._texts.append((setter, key, values))
        setter(t(key, **values))

    def _check(self, key, checked):
        box = QCheckBox()
        box.setChecked(checked)
        self._text(box.setText, key)
        return box

    def _row(self, form, key, widget):
        label = QLabel()
        self._text(label.setText, key)
        form.addRow(label, widget)

    def _tab(self, page, key):
        index = self.tabs.addTab(page, "")
        self._text(lambda text, i=index: self.tabs.setTabText(i, text), key)

    def retranslate(self):
        for setter, key, values in self._texts:
            setter(t(key, **values))
        self.glossary.setPlaceholderText(t("glossary_placeholder"))
        self.speech_source.setItemText(0, t("audio_system"))
        self.speech_source.setItemText(1, t("audio_mic"))
        self.speech_lang.setItemText(0, t("auto_detect"))
        if self.source.itemData(0) == "auto":
            self.source.setItemText(0, t("auto_detect"))
        for i, (name, mb) in enumerate(MODELS.items()):
            self.speech_model.setItemText(i, t("model_size", name=name, mb=mb))
        shown = dict(i18n.available()).get(i18n.current, i18n.current)
        self.language_button.setText(t("language_button", name=shown))
        self._show_toggles()

    def _show_toggles(self, *_):
        self.toggle.setText(t("screen_stop" if self.worker.running else "screen_start"))
        self.speech_toggle.setText(t("speech_stop" if self.speech_enabled.isChecked() else "speech_start"))

    def _fill_language_menu(self):
        menu = self.language_button.menu()
        menu.clear()
        for code, name in i18n.available():
            action = menu.addAction(name)
            action.setCheckable(True)
            action.setChecked(code == i18n.current)
            action.triggered.connect(lambda _=False, code=code: self.set_language(code))

    def set_language(self, code):
        self.ui_language = code
        i18n.load(code)
        self.retranslate()
        self.state.setText(t("state_stopped" if not self.worker.running else "status_running_offline"))
        self.language_changed.emit()
        self.apply()

    @staticmethod
    def _select(combo, data):
        i = combo.findData(data)
        if i >= 0:
            combo.setCurrentIndex(i)

    def current(self):
        return {
            "source": self.source.currentData(), "target": self.target.currentData(),
            "interval": self.interval.value(), "auto_proper": self.auto.isChecked(),
            "keep_katakana": self.kata.isChecked(), "glossary": self.glossary.toPlainText(),
            "hide_from_capture": self.hide_capture.isChecked(),
            "skip_names": self.skip_names.isChecked(),
            "use_google": self.google.isChecked(),
            "autostart": self.autostart.isChecked(), "start_on_launch": self.start_on_launch.isChecked(),
            "speech_enabled": self.speech_enabled.isChecked(), "speech_source": self.speech_source.currentData(),
            "speech_model": self.speech_model.currentData(), "speech_lang": self.speech_lang.currentData(),
            "ui_language": self.ui_language,
        }

    def apply(self, *_):
        s = self.current()
        SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
        self.overlay.set_capture_hidden(s["hide_from_capture"])
        SETTINGS_PATH.write_text(json.dumps(s, ensure_ascii=False, indent=2), encoding="utf-8")
        self.worker.configure(s)
        if self.speech is not None:
            self.speech.configure(s)
            self.captions.set_capture_hidden(s["hide_from_capture"])
        try:
            set_autostart(s["autostart"])
        except OSError:
            pass

    def ensure_packs(self, *_, src=None):
        """Offer to download the offline language packs the chosen pair needs."""
        s = self.current()
        codes = [src] if src else self._source_codes(s)
        missing = sorted({p for code in codes for p in missing_pairs(code, s["target"])})
        if not missing or self.downloading:
            return
        names = ", ".join(f"{a} → {b}" for a, b in missing)
        box = QMessageBox(self)
        box.setWindowTitle(t("packs_title"))
        box.setText(t("packs_text", names=names))
        download = box.addButton(t("btn_download"), QMessageBox.AcceptRole)
        have_file = box.addButton(t("btn_have_file"), QMessageBox.ActionRole)
        box.addButton(t("btn_not_now"), QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() is have_file:
            for path in QFileDialog.getOpenFileNames(self, t("pick_packs"), "", "Argos packs (*.argosmodel)")[0]:
                packs.import_file(path)
            self._packs_ready()
            self.state.setText(t("packs_imported"))
            return
        if box.clickedButton() is not download:
            self.state.setText(t("packs_needed", names=names))
            return
        self.downloading = True
        threading.Thread(target=self._download, args=(missing,), daemon=True).start()

    def _source_codes(self, s):
        """Language codes the screen may be in: the chosen one, or every installed OCR language for auto-detect."""
        supported = set(self.langs.values())
        tags = [tag for tag, _name in ocr.available_languages()] if s["source"] == "auto" else [s["source"]]
        return sorted({ocr_tag_to_code(tag, supported) for tag in tags} - {"auto"})

    def _download(self, pairs):
        try:
            for a, b in pairs:
                self.pack_status.emit(t("pack_downloading", a=a, b=b))
                install_pack(a, b, lambda pct, a=a, b=b: self.pack_status.emit(t("pack_progress", a=a, b=b, pct=pct)))
            self.pack_status.emit(t("packs_installed"))
        except Exception as e:
            self.pack_status.emit(t("download_failed", err=e))
        self.pack_finished.emit()

    def check_for_updates(self, quiet=True):
        """Look for a newer release in the background; offers it if there is one."""
        def run():
            found = updater.check()
            if found:
                self.update_found.emit(found[0], found[1])
            elif not quiet:
                self.pack_status.emit(t("up_to_date"))
        threading.Thread(target=run, daemon=True).start()

    def _offer_update(self, version, url):
        box = QMessageBox(self)
        box.setWindowTitle(t("update_title"))
        box.setText(t("update_text", version=version, current=__version__))
        yes = box.addButton(t("btn_update_now"), QMessageBox.AcceptRole)
        box.addButton(t("btn_later"), QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() is not yes:
            return

        def run():
            try:
                self.update_ready.emit(updater.download(
                    url, lambda pct: self.pack_status.emit(t("update_progress", pct=pct))))
            except Exception as e:
                self.pack_status.emit(t("update_failed", err=e))
        threading.Thread(target=run, daemon=True).start()

    def _run_installer(self, path):
        """Install silently: the app closes, the installer replaces it and starts the new version."""
        subprocess.Popen([path, "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/CLOSEAPPLICATIONS"],
                         creationflags=0x00000008 | 0x00000200, close_fds=True)  # DETACHED_PROCESS | NEW_PROCESS_GROUP
        self.close()

    def _packs_ready(self):
        self.downloading = False
        self.worker.translator.missing_packs.clear()
        self.worker.translator.clear()
        self.worker.dirty = True

    def on_speech_toggle(self, on):
        if self.speech is None:
            return
        if not on:
            self.speech.stop()
            self.captions.clear()
            self.speech_state.setText("")
        elif find_model(self.speech_model.currentData()):
            self._start_speech()
        else:
            self._ask_model(self.speech_model.currentData())

    def _start_speech(self):
        self.speech.configure(self.current())
        lang = self.speech_lang.currentData()
        self.ensure_packs(src=None if lang == "auto" else lang)
        self.speech.start()

    def _restart_speech(self, *_):
        if self.speech is not None and self.speech.running:
            self.speech.stop()
            QTimer.singleShot(800, self._start_speech)

    def _ask_model(self, name):
        """The speech model is a one-time download; the user decides how to get it."""
        box = QMessageBox(self)
        box.setWindowTitle(t("speech_model_title"))
        box.setText(t("speech_model_text", name=name, mb=MODELS[name]))
        download = box.addButton(t("btn_download"), QMessageBox.AcceptRole)
        have_folder = box.addButton(t("btn_have_folder"), QMessageBox.ActionRole)
        box.addButton(t("btn_not_now"), QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() is have_folder:
            folder = QFileDialog.getExistingDirectory(self, t("pick_model_folder"))
            try:
                if not folder:
                    raise RuntimeError(t("no_folder"))
                import_model(folder, name)
                self.speech_model_done.emit(True)
            except Exception as e:
                self.speech_state.setText(t("speech_folder_failed", err=e))
                self.speech_model_done.emit(False)
        elif box.clickedButton() is download:
            self.speech_state.setText(t("speech_downloading", name=name))
            threading.Thread(target=self._download_model, args=(name,), daemon=True).start()
        else:
            self.speech_model_done.emit(False)

    def _download_model(self, name):
        try:
            download_model(name)
            self.speech_model_done.emit(True)
        except Exception as e:
            self.pack_status.emit(t("download_failed", err=e))
            self.speech_model_done.emit(False)

    def _speech_model_done(self, ok):
        if ok:
            self._start_speech()
        else:
            self.speech_enabled.blockSignals(True)
            self.speech_enabled.setChecked(False)
            self.speech_enabled.blockSignals(False)
            self.apply()

    def on_toggle(self):
        if self.worker.running:
            self.worker.stop()
            self._show_toggles()
            self.state.setText(t("state_stopped"))
        else:
            self.apply()
            self.ensure_packs()
            self.worker.start()
            self._show_toggles()
            self.state.setText(t("state_starting"))

    def showEvent(self, e):  # keep this window out of the screenshots too, so it never gets translated
        super().showEvent(e)
        ctypes.windll.user32.SetWindowDisplayAffinity(int(self.winId()), 0x11)

    def closeEvent(self, e):  # the X button quits the whole app
        self.worker.stop()
        if self.speech is not None:
            self.speech.stop()
        e.accept()
        QApplication.quit()


def prewarm(worker):
    """Load the translation model in the background so the first translation is instant."""
    try:
        s = worker.settings
        tags = [t for t, _n in ocr.available_languages()] if s["source"] == "auto" else [s["source"]]
        for tag in tags:
            for pair in needed_pairs(ocr_tag_to_code(tag, set(LANGUAGES.values())), s["target"]):
                if pair in packs.installed_pairs():
                    packs._load(pair)
    except Exception:
        pass


def main():
    lower_priority()
    ensure_streams()
    i18n.load(load_settings()["ui_language"])
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    langs = LANGUAGES
    overlay = Overlay(app.primaryScreen())
    overlay.show()
    chip = CoverChip(overlay)  # noqa: F841 (kept alive; shows itself when a translation covers text)
    worker = Worker(langs)
    worker.overlay_rects = overlay.painted_rects
    worker.background.connect(lambda b: overlay.set_background(*b))
    overlay.set_capture_hidden(worker.settings["hide_from_capture"])
    speech = SpeechWorker()
    captions = CaptionOverlay(app.primaryScreen())
    captions.set_capture_hidden(worker.settings["hide_from_capture"])
    panel = Panel(worker, overlay, langs, speech, captions)
    minimized = "--minimized" in sys.argv
    if not minimized:
        panel.show()
    if worker.settings["start_on_launch"]:
        panel.on_toggle()
    if worker.settings["speech_enabled"] and find_model(worker.settings["speech_model"]):
        panel._start_speech()
    threading.Thread(target=prewarm, args=(worker,), daemon=True).start()
    panel.check_for_updates()

    tray = QSystemTrayIcon(app.style().standardIcon(app.style().StandardPixmap.SP_ComputerIcon), app)
    menu = QMenu()
    show = QAction(menu, triggered=panel.show)
    toggle = QAction(menu, triggered=panel.on_toggle)
    shots = QAction(menu, checkable=True)
    shots.setChecked(not panel.hide_capture.isChecked())
    shots.toggled.connect(lambda on: panel.hide_capture.setChecked(not on))
    panel.hide_capture.toggled.connect(lambda hide: shots.setChecked(not hide))
    talk = QAction(menu, checkable=True)
    talk.setChecked(panel.speech_enabled.isChecked())
    talk.toggled.connect(panel.speech_enabled.setChecked)
    panel.speech_enabled.toggled.connect(talk.setChecked)
    update = QAction(menu, triggered=lambda: panel.check_for_updates(quiet=False))
    quit_ = QAction(menu, triggered=app.quit)
    menu.addActions([show, toggle, talk, shots, update, quit_])

    def retitle_tray():
        for action, key in ((show, "tray_settings"), (toggle, "tray_toggle"), (talk, "tray_speech"),
                            (shots, "tray_shots"), (update, "tray_update"), (quit_, "tray_quit")):
            action.setText(t(key))
    retitle_tray()
    panel.language_changed.connect(retitle_tray)
    tray.setContextMenu(menu)
    tray.activated.connect(lambda r: panel.show() if r == QSystemTrayIcon.Trigger else None)
    tray.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
