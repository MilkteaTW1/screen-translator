"""Update check: asks GitHub for the latest release and, if it is newer, downloads its Windows installer."""
import json
import os
import re
import tempfile
import urllib.request

from . import __version__

API_URL = "https://api.github.com/repos/MilkteaTW1/screen-translator/releases/latest"
INSTALLER_RE = re.compile(r"^ScreenTranslator-Setup-.*\.exe$")


def _version_tuple(text):
    return tuple(int(n) for n in re.findall(r"\d+", text)[:3])


def check(current=__version__):
    """(version, installer_url, notes) of a newer release, or None when up to date or offline."""
    try:
        req = urllib.request.Request(API_URL, headers={"Accept": "application/vnd.github+json",
                                                       "User-Agent": "ScreenTranslator"})
        with urllib.request.urlopen(req, timeout=10) as r:
            release = json.load(r)
        version = release["tag_name"].lstrip("v")
        if release.get("prerelease") or _version_tuple(version) <= _version_tuple(current):
            return None
        asset = next((a for a in release["assets"] if INSTALLER_RE.match(a["name"])), None)
        return (version, asset["browser_download_url"], release.get("body") or "") if asset else None
    except Exception:
        return None


def download(url, progress=None):
    """Download the installer to a temp file and return its path."""
    path = os.path.join(tempfile.mkdtemp(prefix="ScreenTranslator-update-"), url.rsplit("/", 1)[-1])
    with urllib.request.urlopen(url, timeout=60) as r, open(path, "wb") as f:
        total = int(r.headers.get("Content-Length") or 0)
        done = 0
        while chunk := r.read(1 << 16):
            f.write(chunk)
            done += len(chunk)
            if progress and total:
                progress(int(done * 100 / total))
    if total and done < total:
        raise ConnectionError("download was cut off")
    return path
