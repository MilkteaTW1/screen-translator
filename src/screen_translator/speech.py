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
REPOS = {name: f"Systran/faster-whisper-{name}" for name in MODELS}
SILENCE_END = 0.7  # seconds of quiet that end an utterance
SOFT_SEGMENT = 5.0  # seconds: after this, even a short pause ends the utterance (long speech is cut between words)
SOFT_PAUSE = 0.25
MAX_SEGMENT = 12.0  # seconds: cut here whatever happens so captions keep up
MIN_SPEECH = 0.4  # seconds: shorter sounds are clicks, not speech
MAX_BACKLOG = 3  # utterances waiting for transcription; older ones are dropped to stay real-time
PARTIAL_STEP = 0.8  # seconds of new speech between live updates of the sentence being spoken


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
    for snap in sorted((HF_CACHE / ("models--" + REPOS[name].replace("/", "--")) / "snapshots").glob("*")):
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
    snapshot_download(REPOS[name], local_dir=str(MODEL_DIR / name),
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


def normalize(audio, target=0.08, max_gain=30.0):
    """Quiet speech is brought up to a normal level before Whisper hears it (it does far worse on faint audio)."""
    if not len(audio):
        return audio
    rms = float(np.sqrt(np.mean(audio * audio)))
    gain = min(max_gain, max(1.0, target / rms)) if rms > 1e-5 else 1.0
    return np.clip(audio * gain, -1.0, 1.0) if gain > 1.0 else audio


class Segmenter:
    """Cuts a stream of 0.1 s chunks into utterances using an adaptive loudness gate: speech starts when the
    sound rises clearly above the background, and carries on while it stays above a lower level, so quiet
    voices are heard and the soft end of a word is not taken for silence."""

    def __init__(self):
        self.floor = 0.002  # running estimate of the background level
        self.pre = []  # a little audio before speech starts
        self.buf = []
        self.speech = 0.0
        self.quiet = 0.0
        self.fresh = 0.0  # seconds heard since the last live update

    def snapshot(self):
        """The sentence so far (a float32 array) when enough new speech has come in for a live update, else None."""
        if not self.buf or self.speech < MIN_SPEECH or self.fresh < PARTIAL_STEP:
            return None
        self.fresh = 0.0
        return np.concatenate(self.buf)

    def feed(self, chunk):
        """Returns a finished utterance (float32 array) or None."""
        rms = float(np.sqrt(np.mean(chunk * chunk))) if len(chunk) else 0.0
        loud = rms > (max(0.0008, 1.6 * self.floor) if self.buf else max(0.0015, 3 * self.floor))
        if not self.buf and not loud:
            self.floor = 0.95 * self.floor + 0.05 * rms
            self.pre = (self.pre + [chunk])[-3:]
            return None
        if not self.buf:
            self.buf = list(self.pre)
            self.speech = self.quiet = self.fresh = 0.0
        self.buf.append(chunk)
        self.fresh += len(chunk) / SAMPLE_RATE
        if loud:
            self.speech += len(chunk) / SAMPLE_RATE
            self.quiet = 0.0
        else:
            self.quiet += len(chunk) / SAMPLE_RATE
        length = sum(len(c) for c in self.buf) / SAMPLE_RATE
        pause = SOFT_PAUSE if length >= SOFT_SEGMENT else SILENCE_END
        if self.quiet >= pause or length >= MAX_SEGMENT:
            audio = np.concatenate(self.buf)
            enough = self.speech >= MIN_SPEECH
            self.buf, self.pre = [], []
            return audio if enough else None
        return None


def transcribe(model, audio, language=None, beam=1):
    """(text, info) for one utterance."""
    segments, info = model.transcribe(
        normalize(audio), language=language, beam_size=beam, vad_filter=False, condition_on_previous_text=False,
        no_speech_threshold=0.6, without_timestamps=True)
    parts = [seg for seg in segments if seg.no_speech_prob < 0.6 and seg.avg_logprob > -1.5]
    return clean_text(" ".join(seg.text for seg in parts)), info


class SpeechWorker(QObject):
    line = Signal(str, str)  # what was said, its translation ("" when there is none)
    partial = Signal(str, str)  # the same for the sentence still being spoken: shown live, replaced by `line`
    status = Signal(str)

    def __init__(self):
        super().__init__()
        self.translator = Translator()
        self.running = False
        self.settings = {}
        self.audio = queue.Queue()
        self.utterances = queue.Queue()
        self.live = None  # (epoch, audio of the sentence so far): only the latest is kept
        self.epoch = 0  # counts finished sentences, so a late live update of a finished one is dropped

    def configure(self, settings):
        self.settings = settings
        self.translator.google = bool(settings.get("use_google", True))
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
            if utterance is None:
                snap = seg.snapshot()
                if snap is not None:
                    self.live = (self.epoch, snap)
            else:
                self.epoch += 1
                self.live = None
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
                audio = self.utterances.get(timeout=0.1)
            except queue.Empty:
                self._show_live(model)  # nothing finished: work on the sentence being spoken
                continue
            try:
                self._handle(model, audio)
            except Exception as e:
                self.status.emit(t("speech_error", err=e))

    def _translate(self, text, code):
        s = self.settings
        target = s["target"]
        if code == target.split("-")[0].lower():
            return ""
        glossary = [t.strip() for t in s["glossary"].splitlines() if t.strip()]
        translation = self.translator.translate(
            text, {"zh": "zh-CN"}.get(code, code), target, code, glossary, s["auto_proper"], s["keep_katakana"]) or ""
        if not translation and self.translator.missing_packs:
            need = ", ".join(f"{a}→{b}" for a, b in sorted(self.translator.missing_packs))
            self.status.emit(t("speech_packs_needed", names=need))
        return translation

    def _show_live(self, model):
        """Words as they are spoken: transcribe the sentence so far and show it (and its translation) right away.
        When the sentence ends, _handle redoes it with more care and that version replaces this one."""
        live, self.live = self.live, None
        if live is None:
            return
        epoch, audio = live
        language = None if self.settings["speech_lang"] == "auto" else self.settings["speech_lang"]
        text, info = transcribe(model, audio, language)
        if not text or epoch != self.epoch:  # the sentence ended while we were working: its final version is coming
            return
        last = getattr(self, "_last_live", (-1, ""))
        if last[0] == epoch and len(text) < 0.6 * len(last[1]) and not last[1].startswith(text):
            return  # a reading far shorter than the last one and not a part of it: a stumble, keep what is shown
        self._last_live = (epoch, text)
        self.partial.emit(text, self._translate(text, info.language))

    def _handle(self, model, audio):
        s = self.settings
        language = None if s["speech_lang"] == "auto" else s["speech_lang"]
        text, info = transcribe(model, audio, language, beam=2)  # the finished sentence gets the careful pass
        if not text:
            self.partial.emit("", "")  # nothing real was said: drop the live line
            return
        self.line.emit(text, self._translate(text, info.language))
