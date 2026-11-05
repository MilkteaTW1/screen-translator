"""Speech translation: listen to system audio (or the microphone), transcribe offline with Whisper, translate.

Audio never leaves the machine. The Whisper model (faster-whisper / CTranslate2) is downloaded only after the
user agrees, or an existing model folder is reused."""
import os
import queue
import re
import sys
import threading
import time
import types
from pathlib import Path

import numpy as np
from PySide6.QtCore import QObject, Signal

from .i18n import t
from .plat import IS_MAC, data_dir
from .packs import tidy_chinese
from .translator import Translator, server_from_settings

SAMPLE_RATE = 16000
CHUNK = 1600  # 0.1 s of audio per read
LOOPBACK_RE = re.compile(r"blackhole|loopback|soundflower|multi-output|aggregate", re.I)  # macOS virtual audio devices
MODEL_DIR = data_dir() / "whisper"
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
LIVE_TRANSLATE_EVERY = 1.0  # seconds between translations of the sentence being spoken: one request per word got Google to refuse everything
PARTIAL_STEP = 0.3  # seconds of new speech between live updates of the sentence being spoken

# Targets with a script of their own: words already in it need no translation, only the stretches in other scripts do.
_OWN_SCRIPT = {
    "zh": "㐀-䶿一-鿿豈-﫿", "ja": "㐀-䶿一-鿿぀-ヿ", "ko": "가-힣ᄀ-ᇿ", "ru": "Ѐ-ӿ", "uk": "Ѐ-ӿ",
    "bg": "Ѐ-ӿ", "el": "Ͱ-Ͽ", "ar": "؀-ۿ", "he": "֐-׿", "th": "฀-๿", "hi": "ऀ-ॿ",
}
_OWN_RE = {k: re.compile(f"[{v}]") for k, v in _OWN_SCRIPT.items()}


def foreign_runs(text, own):
    """(start, end) of each stretch of letters that are not in the target's own script, with what lies between them
    (spaces, digits, marks) but not what trails them. Words already in the target script are not in any."""
    runs, i, n = [], 0, len(text)
    while i < n:
        if text[i].isalpha() and not own.match(text[i]):
            j = i + 1
            while j < n and not own.match(text[j]):
                j += 1
            end = j
            while end > i and not text[end - 1].isalnum():
                end -= 1
            runs.append((i, end))
            i = j
        else:
            i += 1
    return runs


def mix_translate(text, own, translate_run):
    """The sentence with each stretch that is not in the target's script translated (a stretch that does not translate
    stays as said). "" when there is none: the sentence is already in the target language and is shown as it is."""
    runs = foreign_runs(text, own)
    if not runs:
        return ""
    out, pos = [], 0
    for a, b in runs:
        out.append(text[pos:a])
        out.append(translate_run(text[a:b]) or text[a:b])
        pos = b
    out.append(text[pos:])
    return "".join(out)


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
        self._live_translated_at = 0.0
        self._live_translation = (-1, "")  # (epoch, translation) shown beside the words until the next one is made

    def configure(self, settings):
        self.settings = settings
        self.translator.google = bool(settings.get("use_google", True))
        self.translator.better = settings.get("offline_engine") == "better"
        self.translator.server = server_from_settings(settings)
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
            elif IS_MAC:  # macOS cannot record what it plays by itself: a virtual device (BlackHole) is needed
                device = next((m for m in sc.all_microphones() if LOOPBACK_RE.search(m.name)), None)
                if device is None:
                    raise RuntimeError(t("speech_need_blackhole"))
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
                try:
                    self._show_live(model)  # nothing finished: work on the sentence being spoken
                except Exception as e:  # one bad reading must not end the captions for good
                    self.status.emit(t("speech_error", err=e))
                continue
            try:
                self._handle(model, audio)
            except Exception as e:
                self.status.emit(t("speech_error", err=e))

    def _translate(self, text, code, online=True):
        s = self.settings
        target = s["target"]
        tbase = target.split("-")[0].lower()
        own = _OWN_RE.get(tbase)
        glossary = [t.strip() for t in s["glossary"].splitlines() if t.strip()]

        def run(piece, spoken):
            return self.translator.translate(
                piece, {"zh": "zh-CN"}.get(spoken, spoken), target, spoken, glossary, s["auto_proper"], s["keep_katakana"], online) or ""

        if code == tbase:
            if not own:
                return ""
            # spoken in the target language: only foreign stretches (an English word in a Chinese sentence) are translated
            mixed = mix_translate(text, own, lambda piece: run(piece, "en") if re.search("[A-Za-z]", piece) else "")
            return tidy_chinese(mixed) if tbase == "zh" and mixed else mixed
        if own and not any(c.isalpha() and not own.match(c) for c in text):
            return ""  # every letter is already in the target script (the language guess was wrong): nothing to translate
        translation = run(text, code)
        if not online:
            return translation  # a draft: whatever is wrong is told when the finished sentence is translated
        if not translation and self.translator.missing_packs:
            need = ", ".join(f"{a}→{b}" for a, b in sorted(self.translator.missing_packs))
            self.status.emit(t("speech_packs_needed", names=need))
        elif not translation and (why := self.translator.offline_error or self.translator.google_error):
            self.status.emit(t("speech_no_translation", err=why[:160]))  # heard, but nothing to show: say why
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
        if not self.running:
            return  # stopped while this was being read: it must not put a caption back on the screen
        if not text or epoch != self.epoch:  # the sentence ended while we were working: its final version is coming
            return
        last = getattr(self, "_last_live", (-1, ""))
        if last[0] == epoch and len(text) < 0.6 * len(last[1]) and not last[1].startswith(text):
            return  # a reading far shorter than the last one and not a part of it: a stumble, keep what is shown
        self._last_live = (epoch, text)
        now = time.monotonic()
        if now - self._live_translated_at >= LIVE_TRANSLATE_EVERY:  # not every new word: that is a request each
            self._live_translated_at = now
            # a local draft while the sentence is still being said; the finished sentence goes to Google once
            self._live_translation = (epoch, self._translate(text, info.language, online=False))
        translation = self._live_translation[1] if self._live_translation[0] == epoch else ""
        if self.running:
            self.partial.emit(text, translation)

    def _handle(self, model, audio):
        s = self.settings
        language = None if s["speech_lang"] == "auto" else s["speech_lang"]
        text, info = transcribe(model, audio, language, beam=2)  # the finished sentence gets the careful pass
        if not self.running:
            return
        if not text:
            self.partial.emit("", "")  # nothing real was said: drop the live line
            return
        translation = self._translate(text, info.language)
        if self.running:  # translating can take a while: it may have been stopped meanwhile
            self.line.emit(text, translation)
