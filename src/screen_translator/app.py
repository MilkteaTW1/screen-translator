"""Screen Translator: pick source/target language, translate on-screen text in place, keep proper nouns."""
import ctypes
import winreg
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
from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QFileDialog, QComboBox, QDoubleSpinBox, QFormLayout, QLabel, QLineEdit, QMenu, QMessageBox,
    QPlainTextEdit, QPushButton, QSystemTrayIcon, QVBoxLayout, QWidget,
)

from . import ocr
from .overlay import CaptionOverlay, CoverChip, Overlay
from .speech import MODELS, SpeechWorker, download_model, find_model, import_model
from . import __version__, llm_setup, packs, updater
from .translator import (
    LANGUAGES, Translator, install_pack, looks_like_source, missing_pairs, needed_pairs, ocr_tag_to_code,
)

SETTINGS_PATH = Path(os.environ.get("APPDATA", Path.home())) / "ScreenTranslator" / "settings.json"
DEFAULTS = {
    "source": "en-US", "target": "zh-TW", "interval": 1.0,
    "auto_proper": True, "keep_katakana": False, "glossary": "",
    "hide_from_capture": True, "skip_names": True,
    "autostart": False, "start_on_launch": False,
    "speech_enabled": False, "speech_source": "system", "speech_model": "base", "speech_lang": "auto",
    "llm_enabled": False, "llm_url": "http://localhost:11434/v1", "llm_model": "qwen2.5:7b",
}
MAX_BLOCKS = 40  # most text blocks translated per screen pass
BATCH = 5  # blocks translated between overlay refreshes


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


class Worker(QObject):
    results = Signal(list)
    status = Signal(str)
    background = Signal(tuple)

    def __init__(self, langs):
        super().__init__()
        self.langs = langs  # display name -> language code
        self.settings = load_settings()
        self.translator = Translator()
        self._use_llm(self.settings)
        self.running = False
        self.dirty = True
        self.thread = None
        self.shown = set()  # translations currently on screen, whitespace-stripped
        self.tracks = []  # text blocks followed from scan to scan: position, text, translation, times seen
        self.static = False  # the screen barely changed since the previous scan
        self.origin = (0, 0)  # top-left of the scanned area, added back so the overlay draws in screen coordinates

    def configure(self, settings):
        self.settings = settings
        self._use_llm(settings)
        self.tracks = []
        self.translator.clear()
        self.dirty = True

    def _use_llm(self, s):
        self.translator.llm = (s["llm_url"], s["llm_model"]) if s["llm_enabled"] else None

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
                        gray = (arr[::4, ::4, :3].astype(np.int32) * (114, 587, 299)).sum(axis=2) // 1000  # B, G, R
                        self.background.emit((gray.astype(np.int16), self.origin))
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
        return "Running (local LLM)" if t.engine == "llm" else "Running (offline)"

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
    pack_status = Signal(str)
    pack_finished = Signal()
    speech_model_done = Signal(bool)
    update_found = Signal(str, str)
    update_ready = Signal(str)
    llm_done = Signal(bool)

    def __init__(self, worker, overlay, langs, speech=None, captions=None):
        super().__init__()
        self.worker, self.overlay = worker, overlay
        self.speech, self.captions = speech, captions
        self.langs = langs
        self.downloading = False
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
        self.autostart = QCheckBox("Start with Windows (in the tray)")
        self.autostart.setChecked(s["autostart"])
        self.start_on_launch = QCheckBox("Start translating as soon as the app opens")
        self.start_on_launch.setChecked(s["start_on_launch"])
        self.llm = QCheckBox("Better quality: use a local LLM server (Ollama / LM Studio)")
        self.llm.setChecked(s["llm_enabled"])
        self.llm_url = QLineEdit(s["llm_url"])
        self.llm_model = QLineEdit(s["llm_model"])
        self.llm_install = QPushButton("Install automatically (Ollama + model)")
        self.speech_enabled = QCheckBox("Translate speech: list what is heard at the bottom of the screen")
        self.speech_enabled.setChecked(s["speech_enabled"])
        self.speech_source = QComboBox()
        self.speech_source.addItem("System audio (what the computer plays)", "system")
        self.speech_source.addItem("Microphone", "mic")
        self._select(self.speech_source, s["speech_source"])
        self.speech_model = QComboBox()
        for name, mb in MODELS.items():
            self.speech_model.addItem(f"{name} (about {mb} MB)", name)
        self._select(self.speech_model, s["speech_model"])
        self.speech_lang = QComboBox()
        self.speech_lang.addItem("Auto-detect", "auto")
        seen = set()
        for name, code in sorted(langs.items()):
            base = code.split("-")[0]
            if base not in seen:
                seen.add(base)
                self.speech_lang.addItem(name.title(), base)
        self._select(self.speech_lang, s["speech_lang"])
        self.speech_state = QLabel("")
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
        lay.addWidget(self.autostart)
        lay.addWidget(self.start_on_launch)
        lay.addWidget(self.llm)
        llm_form = QFormLayout()
        llm_form.addRow("Server URL", self.llm_url)
        llm_form.addRow("Model", self.llm_model)
        lay.addLayout(llm_form)
        lay.addWidget(self.llm_install)
        lay.addWidget(self.speech_enabled)
        speech_form = QFormLayout()
        speech_form.addRow("Audio from", self.speech_source)
        speech_form.addRow("Speech language", self.speech_lang)
        speech_form.addRow("Speech model", self.speech_model)
        lay.addLayout(speech_form)
        lay.addWidget(self.speech_state)
        lay.addWidget(QLabel("Do-not-translate list"))
        lay.addWidget(self.glossary)
        lay.addWidget(self.toggle)
        lay.addWidget(self.state)

        for w in (self.source, self.target):
            w.currentIndexChanged.connect(self.apply)
            w.currentIndexChanged.connect(self.ensure_packs)
        self.pack_status.connect(self.state.setText)
        self.pack_finished.connect(self._packs_ready)
        self.update_found.connect(self._offer_update)
        self.update_ready.connect(self._run_installer)
        self.llm_done.connect(self._llm_installed)
        self.llm_install.clicked.connect(self.install_llm)
        self.interval.valueChanged.connect(self.apply)
        self.hide_capture.toggled.connect(self.apply)
        self.skip_names.toggled.connect(self.apply)
        self.auto.toggled.connect(self.apply)
        self.kata.toggled.connect(self.apply)
        self.glossary.textChanged.connect(self.apply)
        self.llm.toggled.connect(self.apply)
        self.autostart.toggled.connect(self.apply)
        self.start_on_launch.toggled.connect(self.apply)
        self.llm_url.editingFinished.connect(self.apply)
        self.llm_model.editingFinished.connect(self.apply)
        worker.status.connect(self.state.setText)
        worker.results.connect(overlay.set_items)
        self.speech_enabled.toggled.connect(self.apply)
        self.speech_enabled.toggled.connect(self.on_speech_toggle)
        for w in (self.speech_source, self.speech_model):
            w.currentIndexChanged.connect(self.apply)
            w.currentIndexChanged.connect(self._restart_speech)
        self.speech_lang.currentIndexChanged.connect(self.apply)
        self.speech_model_done.connect(self._speech_model_done)
        if speech is not None:
            speech.status.connect(self.speech_state.setText)
            speech.line.connect(captions.add)

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
            "skip_names": self.skip_names.isChecked(), "llm_enabled": self.llm.isChecked(),
            "autostart": self.autostart.isChecked(), "start_on_launch": self.start_on_launch.isChecked(),
            "llm_url": self.llm_url.text().strip(), "llm_model": self.llm_model.text().strip(),
            "speech_enabled": self.speech_enabled.isChecked(), "speech_source": self.speech_source.currentData(),
            "speech_model": self.speech_model.currentData(), "speech_lang": self.speech_lang.currentData(),
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
        src = src or ocr_tag_to_code(s["source"], set(self.langs.values()))
        missing = missing_pairs(src, s["target"])
        if not missing or self.downloading:
            return
        names = ", ".join(f"{a} → {b}" for a, b in missing)
        box = QMessageBox(self)
        box.setWindowTitle("Language packs")
        box.setText(f"Translating this pair offline needs: {names}\n"
                    "Each pack is a one-time download of about 50-100 MB. How do you want to get it?")
        download = box.addButton("Download now", QMessageBox.AcceptRole)
        have_file = box.addButton("I have the file...", QMessageBox.ActionRole)
        box.addButton("Not now", QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() is have_file:
            for path in QFileDialog.getOpenFileNames(self, "Pick .argosmodel file(s)", "", "Argos packs (*.argosmodel)")[0]:
                packs.import_file(path)
            self._packs_ready()
            self.state.setText("Language packs imported")
            return
        if box.clickedButton() is not download:
            self.state.setText(f"Offline packs needed: {names}")
            return
        self.downloading = True
        threading.Thread(target=self._download, args=(missing,), daemon=True).start()

    def _download(self, pairs):
        try:
            for a, b in pairs:
                self.pack_status.emit(f"Downloading language pack {a} → {b} ...")
                install_pack(a, b, lambda pct, a=a, b=b: self.pack_status.emit(f"Downloading {a} → {b}: {pct}%"))
            self.pack_status.emit("Language packs installed")
        except Exception as e:
            self.pack_status.emit(f"Download failed: {e}")
        self.pack_finished.emit()

    def install_llm(self):
        url, model = self.llm_url.text().strip(), self.llm_model.text().strip()
        if not llm_setup.is_local(url):
            self.state.setText("Automatic install only works for a server on this computer (localhost)")
            return
        box = QMessageBox(self)
        box.setWindowTitle("Install local LLM")
        box.setText("This installs Ollama (about 1.6 GB) if it is missing, then downloads the model "
                    f"\"{model}\" (several GB). It needs a good amount of free disk space and RAM, "
                    "and can take a while. Everything stays on this computer.")
        yes = box.addButton("Install", QMessageBox.AcceptRole)
        box.addButton("Not now", QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() is not yes:
            return
        self.llm_install.setEnabled(False)

        def run():
            try:
                llm_setup.setup(url, model, self.pack_status.emit)
                self.pack_status.emit("Local LLM ready")
                self.llm_done.emit(True)
            except Exception as e:
                self.pack_status.emit(f"LLM install failed: {e}")
                self.llm_done.emit(False)
        threading.Thread(target=run, daemon=True).start()

    def _llm_installed(self, ok):
        self.llm_install.setEnabled(True)
        if ok:
            self.llm.setChecked(True)

    def check_for_updates(self, quiet=True):
        """Look for a newer release in the background; offers it if there is one."""
        def run():
            found = updater.check()
            if found:
                self.update_found.emit(found[0], found[1])
            elif not quiet:
                self.pack_status.emit("Screen Translator is up to date")
        threading.Thread(target=run, daemon=True).start()

    def _offer_update(self, version, url):
        box = QMessageBox(self)
        box.setWindowTitle("Update available")
        box.setText(f"Screen Translator {version} is available (you have {__version__}).\n"
                    "Download and install it now? The app will close while it installs.")
        yes = box.addButton("Update now", QMessageBox.AcceptRole)
        box.addButton("Later", QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() is not yes:
            return

        def run():
            try:
                self.update_ready.emit(updater.download(
                    url, lambda pct: self.pack_status.emit(f"Downloading update: {pct}%")))
            except Exception as e:
                self.pack_status.emit(f"Update download failed: {e}")
        threading.Thread(target=run, daemon=True).start()

    def _run_installer(self, path):
        os.startfile(path)
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
        box.setWindowTitle("Speech model")
        box.setText(f"Speech translation needs the \"{name}\" speech model (about {MODELS[name]} MB, downloaded once, "
                    "then everything runs offline). How do you want to get it?")
        download = box.addButton("Download now", QMessageBox.AcceptRole)
        have_folder = box.addButton("I have the model folder...", QMessageBox.ActionRole)
        box.addButton("Not now", QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() is have_folder:
            folder = QFileDialog.getExistingDirectory(self, "Pick a faster-whisper model folder (contains model.bin)")
            try:
                if not folder:
                    raise RuntimeError("no folder picked")
                import_model(folder, name)
                self.speech_model_done.emit(True)
            except Exception as e:
                self.speech_state.setText(f"Could not use that folder: {e}")
                self.speech_model_done.emit(False)
        elif box.clickedButton() is download:
            self.speech_state.setText(f"Downloading the {name} speech model ...")
            threading.Thread(target=self._download_model, args=(name,), daemon=True).start()
        else:
            self.speech_model_done.emit(False)

    def _download_model(self, name):
        try:
            download_model(name)
            self.speech_model_done.emit(True)
        except Exception as e:
            self.pack_status.emit(f"Download failed: {e}")
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
            self.toggle.setText("Start")
            self.state.setText("Stopped")
        else:
            self.apply()
            self.ensure_packs()
            self.worker.start()
            self.toggle.setText("Stop")
            self.state.setText("Starting...")

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
        for pair in needed_pairs(ocr_tag_to_code(s["source"], set(LANGUAGES.values())), s["target"]):
            if pair in packs.installed_pairs():
                packs._load(pair)
    except Exception:
        pass


def main():
    lower_priority()
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    langs = LANGUAGES
    overlay = Overlay(app.primaryScreen())
    overlay.show()
    chip = CoverChip(overlay)  # noqa: F841 (kept alive; shows itself when a translation covers text)
    worker = Worker(langs)
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
    show = QAction("Settings", menu, triggered=panel.show)
    toggle = QAction("Start / Stop", menu, triggered=panel.on_toggle)
    shots = QAction("Let screenshots include translations", menu, checkable=True)
    shots.setChecked(not panel.hide_capture.isChecked())
    shots.toggled.connect(lambda on: panel.hide_capture.setChecked(not on))
    panel.hide_capture.toggled.connect(lambda hide: shots.setChecked(not hide))
    talk = QAction("Translate speech", menu, checkable=True)
    talk.setChecked(panel.speech_enabled.isChecked())
    talk.toggled.connect(panel.speech_enabled.setChecked)
    panel.speech_enabled.toggled.connect(talk.setChecked)
    update = QAction("Check for updates", menu, triggered=lambda: panel.check_for_updates(quiet=False))
    quit_ = QAction("Quit", menu, triggered=app.quit)
    menu.addActions([show, toggle, talk, shots, update, quit_])
    tray.setContextMenu(menu)
    tray.activated.connect(lambda r: panel.show() if r == QSystemTrayIcon.Trigger else None)
    tray.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
