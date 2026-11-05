import threading

from screen_translator import app as appmod
from screen_translator import gemma
from screen_translator.translator import Translator


def _fake_gemma(monkeypatch, said):
    monkeypatch.setattr(gemma, "installed", lambda: True)
    monkeypatch.setattr(gemma, "supports", lambda a, b: True)
    monkeypatch.setattr(gemma, "translate_many", lambda texts, a, b: [said + t for t in texts])


def test_a_draft_from_the_standard_packs_is_marked_and_then_replaced_by_the_better_model(monkeypatch):
    _fake_gemma(monkeypatch, "好:")
    tr = Translator()
    tr.gemma = True
    tr._argos_many = lambda texts, s, d: ["草:" + t for t in texts]
    assert tr.translate("Hello there my friend", "en", "zh-TW", "en-US", [], False, False) == "草:Hello there my friend"
    assert ("Hello there my friend", "en", "zh-TW") in tr.drafts
    out = tr.upgrade_many(["Hello there my friend"], "en", "zh-TW", "en-US", [], False, False)
    assert out == ["好:Hello there my friend"]
    assert tr.translate("Hello there my friend", "en", "zh-TW", "en-US", [], False, False) == "好:Hello there my friend"
    assert not tr.drafts  # asked once


def test_without_the_better_model_nothing_is_marked_as_a_draft(monkeypatch):
    monkeypatch.setattr(gemma, "installed", lambda: False)
    tr = Translator()
    tr.gemma = True
    tr._argos_many = lambda texts, s, d: ["草:" + t for t in texts]
    tr.translate("Hello there my friend", "en", "zh-TW", "en-US", [], False, False)
    assert not tr.drafts


def test_google_answers_are_never_sent_to_the_better_model(monkeypatch):
    _fake_gemma(monkeypatch, "好:")
    tr = Translator()
    tr.gemma = tr.google = True
    tr._google_many = lambda items, s, d: {i[0]: "G:" + i[1] for i in items}
    tr.translate("Hello there my friend", "en", "zh-TW", "en-US", [], False, False)
    assert not tr.drafts


def test_many_workers_never_take_the_same_block_twice():
    worker = appmod.Worker(appmod.LANGUAGES)
    tracks = [{"text": f"t{i}"} for i in range(400)]
    worker.tracks = tracks
    worker._upgrades = [(t, ("en", "zh-TW")) for t in tracks]
    taken, lock = [], threading.Lock()

    def work():
        while (c := worker._claim_upgrade()) is not None:
            with lock:
                taken.append(c[0]["text"])

    threads = [threading.Thread(target=work) for _ in range(8)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert sorted(taken) == sorted(t["text"] for t in tracks)  # every block exactly once


def test_a_block_that_scrolled_away_is_not_upgraded():
    worker = appmod.Worker(appmod.LANGUAGES)
    gone = {"text": "gone"}
    worker.tracks = []
    worker._upgrades = [(gone, ("en", "zh-TW"))]
    gone["upgrading"] = True
    assert worker._claim_upgrade() is None and gone["upgrading"] is False
