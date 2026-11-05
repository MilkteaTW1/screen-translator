"""Best offline translation: Google's TranslateGemma 4B (a Gemma 3 model made for translation), run with llama.cpp.
On our test sentences it scores 42 (chrF) against 30 for Qwen2.5 1.5B, 26 for the standard packs and 45 for Google,
at about a second a sentence. A 2.5 GB download the user chooses to make; it runs on this computer only."""
import threading

from . import packs
from .plat import data_dir

NAME = "TranslateGemma 4B"
FILE = "translategemma-4b-it.Q4_K_M.gguf"
URL = "https://huggingface.co/mradermacher/translategemma-4b-it-GGUF/resolve/main/" + FILE
SIZE_MB = 2490
MODEL_DIR = data_dir() / "better" / "translategemma-4b"

# (English name, language code the model's prompt uses) for the Argos codes the app works with
LANGUAGES = {
    "en": ("English", "en"), "zt": ("Traditional Chinese", "zh-Hant"), "zh": ("Simplified Chinese", "zh-Hans"),
    "ja": ("Japanese", "ja"), "ko": ("Korean", "ko"), "fr": ("French", "fr"), "de": ("German", "de"),
    "es": ("Spanish", "es"), "ru": ("Russian", "ru"), "it": ("Italian", "it"), "pt": ("Portuguese", "pt"),
    "th": ("Thai", "th"), "vi": ("Vietnamese", "vi"), "id": ("Indonesian", "id"), "ar": ("Arabic", "ar"),
    "uk": ("Ukrainian", "uk"), "tr": ("Turkish", "tr"), "pl": ("Polish", "pl"), "nl": ("Dutch", "nl"),
    "hi": ("Hindi", "hi"),
}

_model = None
_lock = threading.Lock()  # one translation at a time: the model uses every core it is given


def path():
    return MODEL_DIR / FILE


def installed():
    return path().is_file() and path().stat().st_size > SIZE_MB * 1_000_000 * 0.95


def available():
    """The llama.cpp library is there (it is not on every platform's build)."""
    try:
        import llama_cpp  # noqa: F401
        return True
    except Exception:
        return False


def supports(src, dst):
    return src in LANGUAGES and dst in LANGUAGES


def install(progress=None):
    """Download the model (needs internet; a dropped connection resumes). progress(percent) is optional."""
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    if installed():
        return
    part = MODEL_DIR / (FILE + ".part")
    part.touch()
    packs._fetch(URL, str(part), progress)
    part.replace(path())


def remove():
    global _model
    _model = None
    for f in list(MODEL_DIR.glob("*")):
        try:
            f.unlink()
        except OSError:
            pass


def _load():
    global _model
    if _model is None:
        from llama_cpp import Llama
        _model = Llama(model_path=str(path()), n_ctx=2048, n_threads=max(2, min(8, packs.THREADS * 2)), verbose=False)
    return _model


def _prompt(text, src, dst):
    (sname, scode), (dname, dcode) = LANGUAGES[src], LANGUAGES[dst]
    return (f"<start_of_turn>user\nYou are a professional {sname} ({scode}) to {dname} ({dcode}) translator. Your goal is to "
            f"accurately convey the meaning and nuances of the original {sname} text while adhering to {dname} grammar, "
            f"vocabulary, and cultural sensitivities.\nProduce only the {dname} translation, without any additional "
            f"explanations or commentary. Please translate the following {sname} text into {dname}:\n\n\n"
            f"{text}<end_of_turn>\n<start_of_turn>model\n")


def translate_many(texts, src, dst):
    """One translation per text (a text with several lines is translated line by line, so the line breaks stay)."""
    with _lock:
        model = _load()
        out = []
        for text in texts:
            pieces = []
            for line in (text.splitlines() or [""]):
                line = line.strip()
                if not any(c.isalpha() for c in line):
                    pieces.append(line)
                    continue
                answer = model(_prompt(line, src, dst), max_tokens=min(400, 4 * len(line) + 40), temperature=0,
                               stop=["<end_of_turn>"])["choices"][0]["text"].strip()
                pieces.append(packs.traditional(answer) if dst == "zt" else answer)
            out.append("\n".join(pieces).strip())
        return out
