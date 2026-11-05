"""Optional "better quality" offline translation: a small language model (Qwen2.5 1.5B Instruct, Apache-2.0) run on
CTranslate2, which the app already uses for the standard packs. It is a 1.5 GB download the user chooses to make,
slower than the standard packs (about half a second a sentence) and clearly better at wording, idioms and
words with several meanings. One model covers every language pair, with no detour through English."""
import os
import re
from pathlib import Path

from . import packs
from .plat import data_dir

NAME = "Qwen2.5-1.5B-Instruct"
BASE_URL = "https://huggingface.co/jncraton/Qwen2.5-1.5B-Instruct-ct2-int8/resolve/main/"
FILES = ("config.json", "tokenizer.json", "tokenizer_config.json", "vocabulary.json", "generation_config.json", "model.bin")
SIZE_MB = 1550
MODEL_DIR = data_dir() / "better" / "qwen2.5-1.5b"

LANGUAGE_NAMES = {
    "en": "English", "zt": "Traditional Chinese (Taiwan)", "zh": "Simplified Chinese", "ja": "Japanese", "ko": "Korean",
    "fr": "French", "de": "German", "es": "Spanish", "ru": "Russian", "it": "Italian", "pt": "Portuguese", "th": "Thai",
    "vi": "Vietnamese", "id": "Indonesian", "ar": "Arabic",
}

_model = None


def installed():
    return all((MODEL_DIR / f).is_file() for f in FILES)


def install(progress=None):
    """Download the model (needs internet, about 1.5 GB; a dropped connection resumes). progress(percent) is optional."""
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    for name in FILES:
        target = MODEL_DIR / name
        if target.is_file():
            continue
        part = MODEL_DIR / (name + ".part")
        part.touch()
        packs._fetch(BASE_URL + name, str(part), progress if name == "model.bin" else None)
        part.replace(target)


def remove():
    """Delete the downloaded model."""
    for f in list(MODEL_DIR.glob("*")):
        try:
            f.unlink()
        except OSError:
            pass


def _load():
    global _model
    if _model is None:
        import ctranslate2  # imported late: keeps start-up fast
        from tokenizers import Tokenizer
        generator = ctranslate2.Generator(str(MODEL_DIR), device="cpu", inter_threads=1,
                                          intra_threads=packs.THREADS, compute_type="int8")
        _model = (generator, Tokenizer.from_file(str(MODEL_DIR / "tokenizer.json")))
    return _model


def _prompt(text, src, dst):
    system = (f"You are a professional translator. Translate the user's text from {LANGUAGE_NAMES.get(src, 'the source language')} "
              f"into {LANGUAGE_NAMES.get(dst, dst)}. Keep markers such as Z1Z exactly as they are. Keep numbers, code and "
              "URLs. Output only the translation, with the same line breaks, and no explanation.")
    return f"<|im_start|>system\n{system}<|im_end|>\n<|im_start|>user\n{text}<|im_end|>\n<|im_start|>assistant\n"


def _clean(text, dst):
    text = text.strip()
    if dst == "zt":
        text = packs.traditional(text)
    elif dst == "zh":
        try:
            import zhconv
            text = zhconv.convert(text, "zh-cn")
        except Exception:
            pass
    return re.sub(r"[ \t]+\n", "\n", text)


def translate_many(texts, src, dst):
    """Translate each text from the (src, dst) codes (the Argos ones: zt is Traditional Chinese, zh Simplified).
    A text goes through one line at a time: the model translates a short line reliably, and keeps the line breaks."""
    lines = [text.splitlines() or [""] for text in texts]
    flat = [ln.strip() for ls in lines for ln in ls]
    todo = [i for i, ln in enumerate(flat) if any(c.isalpha() for c in ln)]  # "12345" or "$5" need no translating
    done = {}
    if todo:
        generator, tokenizer = _load()
        prompts = [tokenizer.encode(_prompt(flat[i], src, dst)).tokens for i in todo]
        longest = max(len(tokenizer.encode(flat[i]).ids) for i in todo)
        results = generator.generate_batch(prompts, max_length=min(400, 3 * longest + 24), sampling_topk=1, beam_size=1,
                                           include_prompt_in_result=False, end_token="<|im_end|>", max_batch_size=8)
        for i, result in zip(todo, results):
            done[i] = _clean(tokenizer.decode(result.sequences_ids[0], skip_special_tokens=True), dst).replace(chr(10), " ")
    out, k = [], 0
    for ls in lines:
        pieces = []
        for _ in ls:
            pieces.append(done.get(k, flat[k]))
            k += 1
        out.append(chr(10).join(pieces).strip())
    return out
