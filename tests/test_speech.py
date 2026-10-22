import numpy as np

from screen_translator import speech


def run(stream):
    seg = speech.Segmenter()
    out = []
    for i in range(0, len(stream), speech.CHUNK):
        u = seg.feed(stream[i:i + speech.CHUNK].astype(np.float32))
        if u is not None:
            out.append(u)
    return out


def tone(seconds, level=0.2):
    t = np.arange(int(seconds * speech.SAMPLE_RATE)) / speech.SAMPLE_RATE
    return level * np.sin(2 * np.pi * 220 * t)


def quiet(seconds):
    return np.zeros(int(seconds * speech.SAMPLE_RATE))


def test_one_utterance_between_silences():
    out = run(np.concatenate([quiet(1), tone(2), quiet(2)]))
    assert len(out) == 1
    assert 2.0 <= len(out[0]) / speech.SAMPLE_RATE <= 3.5


def test_two_utterances_are_separated():
    out = run(np.concatenate([quiet(1), tone(1.5), quiet(1.5), tone(1.5), quiet(2)]))
    assert len(out) == 2


def test_clicks_are_ignored():
    assert run(np.concatenate([quiet(1), tone(0.15), quiet(2)])) == []


def test_long_speech_is_cut():
    out = run(np.concatenate([quiet(1), tone(25), quiet(2)]))
    assert len(out) >= 2
    assert all(len(u) / speech.SAMPLE_RATE <= speech.MAX_SEGMENT + 0.5 for u in out)


def test_clean_text_drops_junk():
    assert speech.clean_text(" . ") == ""
    assert speech.clean_text("Hello   there") == "Hello there"
