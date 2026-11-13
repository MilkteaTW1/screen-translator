import json

from screen_translator import updater


class _Reply:
    def __init__(self, data):
        self.data = data

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self, *a):
        return json.dumps(self.data).encode()


def _release(tag, assets=("ScreenTranslator-Setup-%s.exe",), **extra):
    v = tag.lstrip("v")
    return {"tag_name": tag, "assets": [{"name": a % v, "browser_download_url": "https://x/" + a % v} for a in assets], **extra}


def test_releases_lists_installers_newest_first_and_skips_prereleases_and_drafts(monkeypatch):
    data = [_release("v0.6.2"), _release("v0.6.4"), _release("v0.6.5", prerelease=True), _release("v0.6.3"),
            _release("v0.6.1", assets=("ScreenTranslator-%s.apk",)), _release("v0.6.0", draft=True)]
    monkeypatch.setattr(updater.urllib.request, "urlopen", lambda *a, **k: _Reply(data))
    assert [v for v, _ in updater.releases()] == ["0.6.4", "0.6.3", "0.6.2"]  # phone-only, pre-release and draft left out


def test_releases_is_empty_when_offline(monkeypatch):
    def boom(*a, **k):
        raise OSError("offline")
    monkeypatch.setattr(updater.urllib.request, "urlopen", boom)
    assert updater.releases() == []
