from screen_translator import better
from screen_translator.translator import Translator


class FakeResult:
    def __init__(self, ids):
        self.sequences_ids = [ids]


class FakeEncoding:
    def __init__(self, text):
        self.tokens = list(text)
        self.ids = list(range(len(text)))


class FakeTokenizer:
    def encode(self, text):
        return FakeEncoding(text)

    def decode(self, ids, skip_special_tokens=True):
        return "T" + str(len(ids))


class FakeGenerator:
    def __init__(self):
        self.prompts = []

    def generate_batch(self, prompts, **_):
        self.prompts += prompts
        return [FakeResult([0] * i) for i, _p in enumerate(prompts, start=1)]


def test_lines_are_translated_one_by_one_and_keep_their_places(monkeypatch):
    gen = FakeGenerator()
    monkeypatch.setattr(better, "_load", lambda: (gen, FakeTokenizer()))
    out = better.translate_many(["Hello there\n12345\nGood bye", "$5"], "en", "ja")
    assert len(gen.prompts) == 2  # the number-only lines are not sent
    assert out[0].split("\n")[1] == "12345" and out[0].count("\n") == 2
    assert out[1] == "$5"


def test_the_translator_uses_the_better_model_only_when_asked_and_downloaded(monkeypatch):
    monkeypatch.setattr(better, "translate_many", lambda texts, a, b: [f"{a}>{b}:{x}" for x in texts])
    tr = Translator()
    monkeypatch.setattr(better, "installed", lambda: True)
    tr.better = True
    assert tr._argos_many(["hi"], "en", "zh-TW") == ["en>zt:hi"]
    tr.better = False
    assert tr._argos_many(["hi"], "en", "zh-TW") != ["en>zt:hi"]
    tr.better = True
    monkeypatch.setattr(better, "installed", lambda: False)
    assert tr._argos_many(["hi"], "en", "zh-TW") != ["en>zt:hi"]
