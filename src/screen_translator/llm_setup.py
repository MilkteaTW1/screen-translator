"""One-click setup of the optional local LLM: install Ollama, start it, and download the translation model."""
import json
import os
import shutil
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

from .packs import _fetch

OLLAMA_URL = "https://ollama.com/download/OllamaSetup.exe"
EXE_PATH = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "Programs" / "Ollama" / "ollama.exe"


def is_local(url):
    return urlparse(url).hostname in ("localhost", "127.0.0.1", "::1")


def _api(url, path):
    parts = urlparse(url)
    return f"{parts.scheme}://{parts.netloc}{path}"


def models(url):
    """Names of the models the server has, or None when it is not running."""
    try:
        with urllib.request.urlopen(_api(url, "/api/tags"), timeout=3) as r:
            return [m["name"] for m in json.load(r)["models"]]
    except Exception:
        return None


def has_model(url, model):
    names = models(url) or []
    return model in names or f"{model}:latest" in names


def find_exe():
    return shutil.which("ollama") or (str(EXE_PATH) if EXE_PATH.is_file() else None)


def install_ollama(progress=None):
    """Download Ollama's own installer and run it silently. Returns when it has finished."""
    path = os.path.join(tempfile.mkdtemp(prefix="ScreenTranslator-ollama-"), "OllamaSetup.exe")
    open(path, "wb").close()
    _fetch(OLLAMA_URL, path, progress)
    if subprocess.run([path, "/SILENT", "/NORESTART"]).returncode != 0:
        raise RuntimeError("the Ollama installer did not finish")
    if not find_exe():
        raise RuntimeError("Ollama was installed but ollama.exe was not found")


def start(url, wait=40):
    """Make sure the server is answering, starting it if needed."""
    if models(url) is not None:
        return
    subprocess.Popen([find_exe(), "serve"], creationflags=0x08000000 | 0x00000008,  # no window, detached
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(wait):
        if models(url) is not None:
            return
        time.sleep(1)
    raise RuntimeError("Ollama did not start")


def pull(url, model, progress=None):
    """Download a model through the server's API; progress(percent) is optional."""
    req = urllib.request.Request(_api(url, "/api/pull"), data=json.dumps({"model": model}).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        for line in r:
            event = json.loads(line)
            if event.get("error"):
                raise RuntimeError(event["error"])
            if progress and event.get("total"):
                progress(int(event.get("completed", 0) * 100 / event["total"]))
            if event.get("status") == "success":
                return
    if not has_model(url, model):
        raise RuntimeError("the model download was cut off")


def setup(url, model, status):
    """Do whatever is missing. status(text) reports what is happening."""
    if models(url) is None:
        if not find_exe():
            status("Downloading Ollama ...")
            install_ollama(lambda pct: status(f"Downloading Ollama: {pct}%"))
        status("Starting Ollama ...")
        start(url)
    if not has_model(url, model):
        status(f"Downloading model {model} ...")
        pull(url, model, lambda pct: status(f"Downloading model {model}: {pct}%"))
