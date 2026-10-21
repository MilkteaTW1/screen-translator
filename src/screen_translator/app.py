"""Screen Translator: pick source/target language, translate on-screen text in place, keep proper nouns."""
import ctypes
import difflib
import json
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import mss
import numpy as np
from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDoubleSpinBox, QFormLayout, QLabel, QMenu,
    QPlainTextEdit, QPushButton, QSystemTrayIcon, QVBoxLayout, QWidget,
)

from . import ocr
from .overlay import Overlay
from .translator import LANGUAGES, Translator, looks_like_source, ocr_tag_to_code

SETTINGS_PATH = Path(os.environ.get("APPDATA", Path.home())) / "ScreenTranslator" / "settings.json"
DEFAULTS = {
    "source": "en-US", "target": "zh-TW", "interval": 1.0,
    "auto_proper": True, "keep_katakana": False, "glossary": "",
    "hide_from_capture": True, "skip_names": True,
}
MAX_BLOCKS = 40  # most text blocks translated per screen pass
BATCH = 5  # blocks translated between overlay refreshes


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


class Worker(QObject):
    results = Signal(list)
    status = Signal(str)

    def __init__(self, langs):
        super().__init__()
        self.langs = langs  # display name -> language code
        self.settings = load_settings()
        self.translator = Translator()
        self.running = False
        self.dirty = True
        self.thread = None
        self.shown = set()  # translations currently on screen, whitespace-stripped
        self.tracks = []  # text blocks followed from scan to scan: position, text, translation, times seen
        self.static = False  # the screen barely changed since the previous scan
        self.origin = (0, 0)  # top-left of the scanned area, added back so the overlay draws in screen coordinates

    def configure(self, settings):
        self.settings = settings
        self.tracks = []
        self.translator.clear()
        self.dirty = True

    def start(self):
        if self.running:
            return
        self.running = True
        self.dirty = True
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()

    def stop(self):
        self.running = False
        self.results.emit([])

    def _loop(self):
        recognizer, prev = None, None
        pool = ThreadPoolExecutor(2)
        with mss.mss() as sct:
            mon = sct.monitors[1]
            while self.running:
                s = self.settings
                try:
                    if recognizer is None or recognizer.tag != s["source"]:
                        recognizer = ocr.Recognizer(s["source"])
                    region = s.get("region")  # [left, top, width, height]: translate only this part of the screen
                    self.origin = (region[0], region[1]) if region else (0, 0)
                    shot = sct.grab(dict(left=region[0], top=region[1], width=region[2], height=region[3])
                                    if region else mon)
                    arr = np.frombuffer(shot.bgra, np.uint8).reshape(shot.height, shot.width, 4)
                    small = arr[::8, ::8, :3].astype(np.int16)
                    diff = None if prev is None or small.shape != prev.shape else float(np.abs(small - prev).mean())
                    self.static = diff is not None and diff < 2.0  # barely changed: not scrolling or playing video
                    if diff is None or diff > 0.6 or self.dirty:
                        prev, self.dirty = small, False
                        self.results.emit(self._process(recognizer, shot, s, pool))
                        self.status.emit(self._status_text())
                        # Text seen only once is not shown yet: look again soon to confirm it.
                        self.dirty = self.dirty or any(t["seen"] < 2 for t in self.tracks)
                except Exception as e:  # keep the loop alive; show the problem in the UI
                    self.status.emit(f"Error: {e}")
                time.sleep(min(0.4, s["interval"]) if self.dirty else s["interval"])

    def _status_text(self):
        t = self.translator
        if t.missing_packs:
            need = ", ".join(f"{a}→{b}" for a, b in sorted(t.missing_packs))
            return f"Offline packs needed: {need} (run scripts/download_packs.py)"
        return "Running (offline)"

    def _process(self, recognizer, shot, s, pool):
        glossary = [t.strip() for t in s["glossary"].splitlines() if t.strip()]
        everything = recognizer.recognize(shot.bgra, shot.width, shot.height)
        kept = [l for l in everything
                if looks_like_source(l.text, s["source"], l.w, l.h, s["skip_names"])
                and not self._is_own_output(l.text)]
        blocks = ocr.merge_paragraphs(kept, recognizer.joiner)  # translate whole paragraphs, not fragments
        blocks.sort(key=lambda b: (b.y, b.x))
        src = ocr_tag_to_code(s["source"], set(self.langs.values()))
        args = (src, s["target"], s["source"], glossary, s["auto_proper"], s["keep_katakana"])
        kept_ids = {id(l) for l in kept}

        # OCR reads the same text a little differently on every scan (a misread letter, a different
        # line break, a pass where it is missed altogether). Follow each text block from scan to scan
        # as a "track" so that what is on screen stays steady:
        #  - a block that matches an earlier one keeps its translation and position,
        #  - a new block is only shown once it has been seen twice (one-scan noise never appears),
        #  - a shown block that is missed once on a still screen stays (OCR dropout).
        fresh, used = [], set()
        for b in blocks:
            t = self._match_track(b, used)
            if t:
                used.add(id(t))
                t["seen"] += 1
                t["missed"] = 0
                if not self._same_place(t, b):  # it really moved (scrolling): follow it
                    t.update(x=b.x, y=b.y, w=b.w, h=b.h, lh=b.lh)
            else:
                t = {"x": b.x, "y": b.y, "w": b.w, "h": b.h, "lh": b.lh, "text": b.text,
                     "translation": None, "done": False, "seen": 1, "missed": 0}
            fresh.append(t)
        carried = []
        for t in self.tracks:
            if id(t) not in used:
                t["missed"] += 1
                if self.static and t["seen"] >= 2 and t["missed"] <= 1:
                    carried.append(t)
        self.tracks = fresh + carried

        for t in fresh:  # already translated earlier: straight from the cache
            key = (t["text"], src, s["target"])
            if not t["done"] and key in self.translator.cache:
                t["translation"], t["done"] = self.translator.cache[key], True

        def visible(t):
            return t["translation"] if t["seen"] >= 2 and t["done"] else None

        def snapshot():
            # Lines we don't translate are included (text None) so the overlay avoids covering them.
            ox, oy = self.origin
            items = [(l.x + ox, l.y + oy, l.w, l.h, None, l.h) for l in everything if id(l) not in kept_ids]
            items += [(t["x"] + ox, t["y"] + oy, t["w"], t["h"], visible(t), t["lh"]) for t in self.tracks]
            return items

        def update_shown():
            self.shown = {"".join(v.split()) for v in map(visible, self.tracks) if v}

        # Translate top to bottom in small batches and show each batch as it finishes, so a
        # screen full of text fills in progressively instead of freezing until everything is done.
        update_shown()
        todo = [t for t in fresh if not t["done"]][:MAX_BLOCKS]
        for i in range(0, len(todo), BATCH):
            batch = todo[i:i + BATCH]
            for t, out in zip(batch, pool.map(lambda t: self.translator.translate(t["text"], *args), batch)):
                t["translation"], t["done"] = out, True
            update_shown()
            if i + BATCH < len(todo):
                self.results.emit(snapshot())
                if not self.running or self.dirty:  # the user changed something: restart with fresh settings
                    break
        return snapshot()

    def _match_track(self, block, used):
        """The earlier text block this one most likely is: overlapping area and nearly the same text."""
        best, best_iou = None, 0.5
        for t in self.tracks:
            if id(t) in used:
                continue
            iou = _iou((block.x, block.y, block.w, block.h), (t["x"], t["y"], t["w"], t["h"]))
            if iou > best_iou and difflib.SequenceMatcher(None, block.text, t["text"]).ratio() >= 0.8:
                best, best_iou = t, iou
        return best

    @staticmethod
    def _same_place(track, b):
        return (abs(track["x"] - b.x) <= 8 and abs(track["y"] - b.y) <= 8
                and abs(track["w"] - b.w) <= 12 and abs(track["h"] - b.h) <= 12)

    def _is_own_output(self, text):
        """True if OCR picked up one of our own translations (guards against re-translating them)."""
        norm = "".join(text.split())
        return any(difflib.SequenceMatcher(None, norm, s).ratio() >= 0.7 for s in self.shown)


class Panel(QWidget):
    def __init__(self, worker, overlay, langs):
        super().__init__()
        self.worker, self.overlay = worker, overlay
        self.setWindowTitle("Screen Translator")
        self.setMinimumWidth(380)
        s = worker.settings

        self.source = QComboBox()
        installed = ocr.available_languages()
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
        self.auto = QCheckBox("Auto-detect proper nouns (Capitalized / ALL CAPS / CamelCase)")
        self.auto.setChecked(s["auto_proper"])
        self.kata = QCheckBox("Japanese: keep ALL katakana untranslated (also loanwords like タワー)")
        self.kata.setChecked(s["keep_katakana"])
        self.hide_capture = QCheckBox("Hide translations from screenshots")
        self.hide_capture.setChecked(s["hide_from_capture"])
        self.skip_names = QCheckBox("Skip names and one-word labels (e.g. Bill Gates, Premium)")
        self.skip_names.setChecked(s["skip_names"])
        self.glossary = QPlainTextEdit(s["glossary"])
        self.glossary.setPlaceholderText("Never translate these (one per line)\ne.g. Hatsune Miku\nNVIDIA")
        self.toggle = QPushButton("Start")
        self.toggle.clicked.connect(self.on_toggle)
        self.state = QLabel("Stopped")

        form = QFormLayout()
        form.addRow("Screen language", self.source)
        form.addRow("Translate to", self.target)
        form.addRow("Refresh interval", self.interval)
        lay = QVBoxLayout(self)
        lay.addLayout(form)
        lay.addWidget(self.hide_capture)
        lay.addWidget(self.skip_names)
        lay.addWidget(self.auto)
        lay.addWidget(self.kata)
        lay.addWidget(QLabel("Do-not-translate list"))
        lay.addWidget(self.glossary)
        lay.addWidget(self.toggle)
        lay.addWidget(self.state)

        for w in (self.source, self.target):
            w.currentIndexChanged.connect(self.apply)
        self.interval.valueChanged.connect(self.apply)
        self.hide_capture.toggled.connect(self.apply)
        self.skip_names.toggled.connect(self.apply)
        self.auto.toggled.connect(self.apply)
        self.kata.toggled.connect(self.apply)
        self.glossary.textChanged.connect(self.apply)
        worker.status.connect(self.state.setText)
        worker.results.connect(overlay.set_items)

        if not installed:
            self.state.setText("No OCR language packs installed in Windows")
            self.toggle.setEnabled(False)

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
        }

    def apply(self, *_):
        s = self.current()
        SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
        self.overlay.set_capture_hidden(s["hide_from_capture"])
        SETTINGS_PATH.write_text(json.dumps(s, ensure_ascii=False, indent=2), encoding="utf-8")
        self.worker.configure(s)

    def on_toggle(self):
        if self.worker.running:
            self.worker.stop()
            self.toggle.setText("Start")
            self.state.setText("Stopped")
        else:
            self.apply()
            self.worker.start()
            self.toggle.setText("Stop")
            self.state.setText("Starting...")

    def showEvent(self, e):  # keep this window out of the screenshots too, so it never gets translated
        super().showEvent(e)
        ctypes.windll.user32.SetWindowDisplayAffinity(int(self.winId()), 0x11)

    def closeEvent(self, e):  # the X button quits the whole app
        self.worker.stop()
        e.accept()
        QApplication.quit()


def main():
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    langs = LANGUAGES
    overlay = Overlay(app.primaryScreen())
    overlay.show()
    worker = Worker(langs)
    overlay.set_capture_hidden(worker.settings["hide_from_capture"])
    panel = Panel(worker, overlay, langs)
    panel.show()

    tray = QSystemTrayIcon(app.style().standardIcon(app.style().StandardPixmap.SP_ComputerIcon), app)
    menu = QMenu()
    show = QAction("Settings", menu, triggered=panel.show)
    toggle = QAction("Start / Stop", menu, triggered=panel.on_toggle)
    shots = QAction("Let screenshots include translations", menu, checkable=True)
    shots.setChecked(not panel.hide_capture.isChecked())
    shots.toggled.connect(lambda on: panel.hide_capture.setChecked(not on))
    panel.hide_capture.toggled.connect(lambda hide: shots.setChecked(not hide))
    quit_ = QAction("Quit", menu, triggered=app.quit)
    menu.addActions([show, toggle, shots, quit_])
    tray.setContextMenu(menu)
    tray.activated.connect(lambda r: panel.show() if r == QSystemTrayIcon.Trigger else None)
    tray.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
