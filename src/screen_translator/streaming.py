"""Streaming speech recognition (sherpa-onnx): the words come out while they are still being spoken, 0.2-0.3 s behind
the voice, instead of after a whole sentence has been read (Whisper needs 1 s or more for every reading). The models
are small transducers that run on the CPU; they are downloaded once, after the user agrees."""
import re

from .plat import data_dir

STREAM_DIR = data_dir() / "stream"

# key -> Hugging Face repo, the files needed (encoder, decoder, joiner, tokens), size in MB, spoken languages it reads
MODELS = {
    "zh-en": dict(repo="csukuangfj/sherpa-onnx-streaming-zipformer-bilingual-zh-en-2023-02-20", mb=200,
                  files=("encoder-epoch-99-avg-1.int8.onnx", "decoder-epoch-99-avg-1.int8.onnx",
                         "joiner-epoch-99-avg-1.int8.onnx", "tokens.txt"), langs=("zh", "en")),
    "en": dict(repo="csukuangfj/sherpa-onnx-streaming-zipformer-en-2023-06-26", mb=72,
               files=("encoder-epoch-99-avg-1-chunk-16-left-128.int8.onnx", "decoder-epoch-99-avg-1-chunk-16-left-128.int8.onnx",
                      "joiner-epoch-99-avg-1-chunk-16-left-128.int8.onnx", "tokens.txt"), langs=("en",)),
    "ko": dict(repo="k2-fsa/sherpa-onnx-streaming-zipformer-korean-2024-06-16", mb=132,
               files=("encoder-epoch-99-avg-1.int8.onnx", "decoder-epoch-99-avg-1.int8.onnx",
                      "joiner-epoch-99-avg-1.int8.onnx", "tokens.txt"), langs=("ko",)),
    "multi": dict(repo="csukuangfj/sherpa-onnx-streaming-zipformer-ar_en_id_ja_ru_th_vi_zh-2025-02-10", mb=340,
                  files=("encoder-epoch-75-avg-11-chunk-16-left-128.int8.onnx", "decoder-epoch-75-avg-11-chunk-16-left-128.onnx",
                         "joiner-epoch-75-avg-11-chunk-16-left-128.int8.onnx", "tokens.txt"),
                  langs=("ja", "ru", "th", "vi", "ar", "id")),
}


def key_for(language):
    """The streaming model that reads the spoken [language] (a code), or None when only Whisper can. "auto" starts on
    the eight-language one (words at once, no matter which of them is spoken); AutoLanguage moves it to another reader
    when a language outside those is heard."""
    if language == "auto":
        return "multi"
    if language in ("zh", "en"):
        return "en" if language == "en" else "zh-en"
    for key, m in MODELS.items():
        if language in m["langs"]:
            return key
    return None


AUTO_LANGS = frozenset(("en", "zh") + MODELS["multi"]["langs"])  # what the "auto" streaming model reads


def usable_key(language):
    """key_for, but "auto" takes a model that is already downloaded (the older English/Chinese one too) before asking for the big one."""
    if language == "auto":
        return next((k for k in ("multi", "zh-en") if find(k)), "multi")
    return key_for(language)


def find(key):
    """Folder of the downloaded model, or None."""
    folder = STREAM_DIR / key
    return folder if all((folder / f).is_file() for f in MODELS[key]["files"]) else None


def download(key):
    """Download a model (needs internet; see MODELS for the size). Raises on failure."""
    from .speech import ensure_streams
    ensure_streams()
    import os
    os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
    from huggingface_hub import hf_hub_download
    folder = STREAM_DIR / key
    folder.mkdir(parents=True, exist_ok=True)
    for name in MODELS[key]["files"]:
        if not (folder / name).is_file():
            hf_hub_download(MODELS[key]["repo"], name, local_dir=str(folder))


def tidy(text):
    """The models write English in capitals: sentence case instead (Chinese is left as it is)."""
    text = " ".join(text.split())
    if text and text.upper() == text and re.search("[A-Z]", text):
        text = re.sub(r"\bi\b", "I", text.lower())
        text = text[:1].upper() + text[1:]
    return text


_SCRIPTS = (("ja", "[぀-ヿ]"), ("zh", "[㐀-鿿]"), ("th", "[฀-๿]"), ("ru", "[Ѐ-ӿ]"), ("ar", "[؀-ۿ]"))


def guess_language(text, spoken):
    """The language code of what was recognised: the chosen one, or for 'auto' read from the letters (Latin letters are
    taken for English, or Vietnamese when they carry its marks; Indonesian is only known when it is chosen)."""
    if spoken != "auto":
        return spoken
    for code, letters in _SCRIPTS:
        if re.search(letters, text):
            return code
    return "vi" if re.search("[ăâđêôơưạảấầẩẫậắằẳẵặẹẻẽếềểễệỉịọỏốồổỗộớờởỡợụủứừửữựỳỵỷỹ]", text.lower()) else "en"


class AutoLanguage:
    """For "auto" speech: the English/Chinese streaming model starts at once, and Whisper listens to the sentences it
    finishes. This says when another language is being spoken, so the captions can move to a reader that knows it."""
    MIN_PROB = 0.6  # a guess weaker than this counts for nothing
    SURE_PROB = 0.9  # one sentence this sure is enough; weaker ones must repeat

    def __init__(self):
        self.sentences = 0
        self.other = None  # the not English/Chinese language of the last guess, and how often it came in a row
        self.times = 0

    def due(self):
        """True when this finished sentence should be checked: all of the first three, then one in four (Whisper costs CPU)."""
        self.sentences += 1
        return self.sentences <= 3 or self.sentences % 4 == 0

    def add(self, language, prob):
        """Feed one guess; returns the language code to move to, or None to stay."""
        language = "zh" if language in ("yue", "zh") else language
        if prob < self.MIN_PROB:
            return None
        if language in AUTO_LANGS:  # the captions already read it
            self.other, self.times = None, 0
            return None
        self.times = self.times + 1 if language == self.other else 1
        self.other = language
        return language if prob >= self.SURE_PROB or self.times >= 2 else None


class Stream:
    """One recogniser: feed 0.1 s chunks, get the text so far and whether the sentence just ended."""

    def __init__(self, key, threads=2):
        import sherpa_onnx
        folder = STREAM_DIR / key
        enc, dec, joi, tok = (str(folder / f) for f in MODELS[key]["files"])
        self.recognizer = sherpa_onnx.OnlineRecognizer.from_transducer(
            tokens=tok, encoder=enc, decoder=dec, joiner=joi, num_threads=threads, sample_rate=16000,
            enable_endpoint_detection=True,
            rule1_min_trailing_silence=0.8,  # nothing recognised yet and this much quiet: reset
            rule2_min_trailing_silence=0.5,  # a sentence was said and this much quiet: it is over
            rule3_min_utterance_length=10.0)  # long talk without a pause is cut here
        self.stream = self.recognizer.create_stream()

    def feed(self, chunk):
        """(text so far, True when the sentence ended). After an end the stream starts over."""
        self.stream.accept_waveform(16000, chunk)
        while self.recognizer.is_ready(self.stream):
            self.recognizer.decode_stream(self.stream)
        text = tidy(self.recognizer.get_result(self.stream))
        ended = self.recognizer.is_endpoint(self.stream)
        if ended:
            self.recognizer.reset(self.stream)
        return text, ended
