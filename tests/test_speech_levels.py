import numpy as np

from screen_translator import speech


def feed(audio):
    seg, out = speech.Segmenter(), []
    for i in range(0, len(audio), speech.CHUNK):
        u = seg.feed(audio[i:i + speech.CHUNK])
        if u is not None:
            out.append(u)
    return out


def voice(seconds, level, rate=16000):
    t = np.arange(int(seconds * rate)) / rate
    return (level * np.sin(2 * np.pi * 180 * t) * (0.6 + 0.4 * np.sin(2 * np.pi * 3 * t))).astype(np.float32)


def stream(speech_part):
    quiet = np.random.default_rng(0).normal(0, 0.001, 16000 * 2).astype(np.float32)
    return np.concatenate([quiet, speech_part, quiet])


def test_quiet_speech_is_still_heard():
    for level in (0.2, 0.03, 0.008):  # the last one is below the old fixed gate (rms 0.01) and was never heard
        assert len(feed(stream(voice(3, level)))) == 1, level


def test_background_noise_alone_is_not_speech():
    assert feed(np.random.default_rng(1).normal(0, 0.003, 16000 * 5).astype(np.float32)) == []


def test_long_speech_is_cut_at_a_pause_not_in_the_middle_of_a_word():
    a, b = voice(6.5, 0.1), voice(4, 0.1)
    gap = np.zeros(int(0.3 * 16000), np.float32)  # a short breath: too short to end an utterance on its own
    parts = feed(stream(np.concatenate([a, gap, b])))
    assert len(parts) == 2 and abs(len(parts[0]) / 16000 - 7.0) < 1.0


def test_quiet_audio_is_brought_up_before_transcription_but_loud_audio_is_left_alone():
    quiet, loud = voice(2, 0.01), voice(2, 0.4)
    assert np.sqrt(np.mean(speech.normalize(quiet) ** 2)) > 0.05
    assert np.array_equal(speech.normalize(loud), loud)
    assert np.abs(speech.normalize(quiet)).max() <= 1.0
