"""Lightweight offline translation: runs Argos language packs straight on CTranslate2 + SentencePiece.

The Argos Translate library itself is not used at run time (it drags in torch and spacy, which makes
the app large, slow to start and hungry). Packs are the same `.argosmodel` files, so ones already
installed by Argos are found too."""
import http.client
import json
import os
import re
import tempfile
import time
import urllib.request
import zipfile
from pathlib import Path

INDEX_URL = "https://raw.githubusercontent.com/argosopentech/argospm-index/main/index.json"
PACK_DIR = Path(os.environ.get("APPDATA", Path.home())) / "ScreenTranslator" / "packs"
LEGACY_DIR = Path.home() / ".local" / "share" / "argos-translate" / "packages"
SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?。！？])\s+|(?<=[。！？])")
THREADS = max(2, min(4, (os.cpu_count() or 4) // 2 - 1))  # CPU threads one translation may use: few, so the app stays light
BEAM = 2

_models = {}


def _pack_dirs():
    for base in (PACK_DIR, LEGACY_DIR):
        if base.is_dir():
            yield from (d for d in base.iterdir() if (d / "metadata.json").is_file())


def installed_pairs():
    """{(from_code, to_code): pack directory} for every pack on disk."""
    pairs = {}
    for d in _pack_dirs():
        try:
            meta = json.loads((d / "metadata.json").read_text(encoding="utf-8"))
            if (d / "model").is_dir() and (d / "sentencepiece.model").is_file():
                pairs.setdefault((meta["from_code"], meta["to_code"]), d)
        except Exception:
            continue
    return pairs


def _load(pair):
    if pair not in _models:
        import ctranslate2  # imported late: keeps start-up fast
        import sentencepiece
        d = installed_pairs()[pair]
        meta = json.loads((d / "metadata.json").read_text(encoding="utf-8"))
        translator = ctranslate2.Translator(str(d / "model"), device="cpu", inter_threads=1,
                                            intra_threads=THREADS, compute_type="int8")
        _models[pair] = (translator, sentencepiece.SentencePieceProcessor(str(d / "sentencepiece.model")),
                         meta.get("target_prefix", ""))
    return _models[pair]


def translate_many(texts, src, dst):
    """Translate blocks of text with the (src, dst) pack. All their sentences go through the engine in ONE
    call: the engine is much faster that way than one call per block."""
    translator, sp, prefix = _load((src, dst))
    split = [[s for s in SENTENCE_SPLIT_RE.split(t.strip()) if s.strip()] for t in texts]
    flat = [s for sentences in split for s in sentences]
    if not flat:
        return [""] * len(texts)
    tokens = [sp.encode(s, out_type=str) for s in flat]
    out = translator.translate_batch(
        tokens, target_prefix=[[prefix]] * len(tokens) if prefix else None, replace_unknowns=True,
        beam_size=BEAM, length_penalty=0.2, max_batch_size=1024, batch_type="tokens")
    decoded = []
    for r in out:
        value = sp.decode_pieces(r.hypotheses[0]).replace("▁", " ").replace("_", " ")
        if prefix and value.startswith(prefix):
            value = value[len(prefix):]
        decoded.append(value.strip())
    results, i = [], 0
    for sentences in split:
        pieces = decoded[i:i + len(sentences)]
        i += len(sentences)
        if not pieces:
            results.append("")
            continue
        joiner = "" if re.search(r"[぀-ヿ㐀-鿿]", pieces[0]) else " "
        results.append(re.sub(r"\s+([。，！？、：；])", r"\1", joiner.join(pieces)))
    return results


def translate(text, src, dst):
    """Translate one block of text with the (src, dst) pack."""
    return translate_many([text], src, dst)[0]


def import_file(path):
    """Install a pack from a `.argosmodel` file the user already has (no internet needed)."""
    PACK_DIR.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path) as z:
        z.extractall(PACK_DIR)
    _models.clear()


def _fetch(url, path, progress=None, attempts=4):
    """Download url into path, resuming from what is already there after a dropped connection."""
    for attempt in range(attempts):
        have = os.path.getsize(path)
        req = urllib.request.Request(url, headers={"Range": f"bytes={have}-"} if have else {})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                if have and r.status != 206:  # server ignored Range: start over
                    have = 0
                total = have + int(r.headers.get("Content-Length") or 0)
                with open(path, "ab" if have else "wb") as f:
                    while chunk := r.read(1 << 16):
                        f.write(chunk)
                        have += len(chunk)
                        if progress and total:
                            progress(min(100, int(have * 100 / total)))
            if total and have < total:  # connection dropped mid-file without an error
                raise ConnectionError("download was cut off")
            return
        except (OSError, http.client.HTTPException):
            if attempt == attempts - 1:
                raise
            time.sleep(2 * (attempt + 1))


def install(src, dst, progress=None):
    """Download one pack (needs internet; tens of MB) into PACK_DIR. progress(percent) is optional."""
    with urllib.request.urlopen(INDEX_URL, timeout=30) as r:
        index = json.load(r)
    entry = next((e for e in index if e.get("type", "translate") == "translate"
                  and e["from_code"] == src and e["to_code"] == dst), None)
    if entry is None:
        raise RuntimeError(f"no such language pack: {src}>{dst}")
    PACK_DIR.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(suffix=".argosmodel")
    os.close(fd)
    try:
        _fetch(entry["links"][0], tmp, progress)
        with zipfile.ZipFile(tmp) as z:
            if z.testzip() is not None:
                raise RuntimeError("downloaded pack is corrupt, please try again")
            z.extractall(PACK_DIR)
    finally:
        os.unlink(tmp)
    _models.pop((src, dst), None)
