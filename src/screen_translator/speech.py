"""Speech translation: listen to system audio (or the microphone), transcribe offline with Whisper, translate.

Audio never leaves the machine. The Whisper model (faster-whisper / CTranslate2) is downloaded only after the
user agrees, or an existing model folder is reused."""
import os
import queue
import sys
import threading
import time
import types
from pathlib import Path

import numpy as np
from PySide6.QtCore import QObject, Signal

from .i18n import t
from .translator import Translator

SAMPLE_RATE = 16000
CHUNK = 1600  # 0.1 s of audio per read
MODEL_DIR = Path(os.environ.get("APPDATA", Path.home())) / "ScreenTranslator" / "whisper"
HF_CACHE = Path.home() / ".cache" / "huggingface" / "hub"
# Multilingual Whisper models (Systran/faster-whisper-<name>) and their download size in MB.
MODELS = {"tiny": 75, "base": 145, "small": 485}
SILENCE_END = 0.7  # seconds of quiet that end an utterance
MAX_SEGMENT = 10.0  # seconds: cut long speech here so captions keep up
MIN_SPEECH = 0.4  # seconds: shorter sounds are clicks, not speech
MAX_BACKLOG = 3  # utterances waiting for transcription; older ones are dropped to stay real-time


def whisper_model_class():
    """faster-whisper imports PyAV (ffmpeg, 65 MB) only to decode audio files, which we never do: the packaged
    build leaves it out, so give the import an empty stand-in."""
    try:
        import av  # noqa: F401
    except ImportError:
        sys.modules["av"] = types.ModuleType("av")
    from faster_whisper import WhisperModel
    return WhisperModel


def find_model(name):
    """Folder of an installed model, in our own folder or the Hugging Face cache, or None."""
    own = MODEL_DIR / name
    if (own / "model.bin").is_file():
        return own
    for snap in sorted((HF_CACHE / f"models--Systran--faster-whisper-{name}" / "snapshots").glob("*")):
        if (snap / "model.bin").is_file():
            return snap
    return None


def ensure_streams():
    """A windowed (no console) build has no stdout/stderr, and the download library's progress bar writes to
    them ('NoneType' object has no attribute 'write'): give it somewhere to write."""
    for name in ("stdout", "stderr"):
        if getattr(sys, name) is None:
            setattr(sys, name, open(os.devnull, "w", encoding="utf-8"))


def download_model(name):
    """Download a model (needs internet; see MODELS for the size). Raises on failure."""
    ensure_streams()
    os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
    from huggingface_hub import snapshot_download
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    snapshot_download(f"Systran/faster-whisper-{name}", local_dir=str(MODEL_DIR / name),
                      allow_patterns=["config.json", "model.bin", "tokenizer.json", "vocabulary.*", "preprocessor_config.json"])


def import_model(folder, name):
    """Use a model folder the user already has (it must contain model.bin) without downloading."""
    folder = Path(folder)
    if not (folder / "model.bin").is_file():
        raise RuntimeError("that folder has no model.bin")
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    target = MODEL_DIR / name
    if target.exists():
        raise RuntimeError(f"{target} already exists")
    import shutil
    shutil.copytree(folder, target)


def clean_text(text):
    """Whisper hallucinates on near-silence: filter the usual junk."""
    t = " ".join(text.split())
    if len(t) < 2 or not any(c.isalnum() for c in t):
        return ""
    return t


class Segmenter:
    """Cuts a stream of 0.1 s chunks into utterances using a simple adaptive loudness gate."""

    def __init__(self):
        self.floor = 0.005  # running estimate of the background level
        self.pre = []  # a little audio before speech starts
        self.buf = []
        self.speech = 0.0
        self.quiet = 0.0

    def feed(self, chunk):
        """Returns a finished utterance (float32 array) or None."""
        rms = float(np.sqrt(np.mean(chunk * chunk))) if len(chunk) else 0.0
        loud = rms > max(0.01, 3 * self.floor)
        if not self.buf and not loud:
            self.floor = 0.95 * self.floor + 0.05 * rms
            self.pre = (self.pre + [chunk])[-3:]
            return None
        if not self.buf:
            self.buf = list(self.pre)
            self.speech = self.quiet = 0.0
        self.buf.append(chunk)
        if loud:
            self.speech += len(chunk) / SAMPLE_RATE
            self.quiet = 0.0
        else:
            self.quiet += len(chunk) / SAMPLE_RATE
        length = sum(len(c) for c in self.buf) / SAMPLE_RATE
        if self.quiet >= SILENCE_END or length >= MAX_SEGMENT:
            audio = np.concatenate(self.buf)
            enough = self.speech >= MIN_SPEECH
            self.buf, self.pre = [], []
            return audio if enough else None
        return None


class SpeechWorker(QObject):
    line = Signal(str, str)  # what was said, its translation ("" when there is none)
    status = Signal(str)

    def __init__(self):
        super().__init__()
        self.translator = Translator()
        self.running = False
        self.settings = {}
        self.audio = queue.Queue()
        self.utterances = queue.Queue()

    def configure(self, settings):
        self.settings = settings
        self.translator.llm = (settings["llm_url"], settings["llm_model"]) if settings["llm_enabled"] else None
        self.translator.clear()

    def start(self):
        if self.running:
            return
        self.running = True
        for target in (self._capture, self._segment, self._transcribe):
            threading.Thread(target=target, daemon=True).start()

    def stop(self):
        self.running = False

    def _capture(self):
        try:
            import soundcard as sc
            s = self.settings
            if s["speech_source"] == "mic":
                device = sc.default_microphone()
            else:  # what the computer plays: the loopback of the default speakers
                device = sc.get_microphone(sc.default_speaker().name, include_loopback=True)
            self.status.emit(t("speech_listening"))
            with device.recorder(samplerate=SAMPLE_RATE, channels=1, blocksize=CHUNK) as rec:
                while self.running:
                    self.audio.put(rec.record(numframes=CHUNK)[:, 0].astype(np.float32))
        except Exception as e:
            self.running = False
            self.status.emit(t("speech_audio_error", err=e))

    def _segment(self):
        seg = Segmenter()
        while self.running:
            try:
                chunk = self.audio.get(timeout=0.5)
            except queue.Empty:
                continue
            utterance = seg.feed(chunk)
            if utterance is not None:
                while self.utterances.qsize() >= MAX_BACKLOG:
                    try:
                        self.utterances.get_nowait()
                    except queue.Empty:
                        break
                self.utterances.put(utterance)

    def _transcribe(self):
        try:
            WhisperModel = whisper_model_class()
            path = find_model(self.settings["speech_model"])
            if path is None:
                raise RuntimeError("speech model is not installed")
            self.status.emit(t("speech_loading"))
            model = WhisperModel(str(path), device="cpu", compute_type="int8", cpu_threads=3)
        except Exception as e:
            self.running = False
            self.status.emit(t("speech_model_error", err=e))
            return
        self.status.emit(t("speech_listening"))
        while self.running:
            try:
                audio = self.utterances.get(timeout=0.5)
            except queue.Empty:
                continue
            try:
                self._handle(model, audio)
            except Exception as e:
                self.status.emit(t("speech_error", err=e))

    def _handle(self, model, audio):
        s = self.settings
        language = None if s["speech_lang"] == "auto" else s["speech_lang"]
        segments, info = model.transcribe(
            audio, language=language, beam_size=1, vad_filter=False, condition_on_previous_text=False,
            no_speech_threshold=0.6, without_timestamps=True)
        parts = [seg for seg in segments if seg.no_speech_prob < 0.6 and seg.avg_logprob > -1.2]
        text = clean_text(" ".join(seg.text for seg in parts))
        if not text:
            return
        code = info.language
        target = s["target"]
        translation = ""
        if code != target.split("-")[0].lower():
            glossary = [t.strip() for t in s["glossary"].splitlines() if t.strip()]
            translation = self.translator.translate(
                text, {"zh": "zh-CN"}.get(code, code), target, code, glossary, s["auto_proper"], s["keep_katakana"]) or ""
            if not translation and self.translator.missing_packs:
                need = ", ".join(f"{a}→{b}" for a, b in sorted(self.translator.missing_packs))
                self.status.emit(t("speech_packs_needed", names=need))
        self.line.emit(text, translation)
