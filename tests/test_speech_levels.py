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


def test_live_snapshots_come_while_speaking_and_not_in_silence():
    seg, shots = speech.Segmenter(), []
    audio = stream(voice(4, 0.1))
    for i in range(0, len(audio), speech.CHUNK):
        seg.feed(audio[i:i + speech.CHUNK])
        snap = seg.snapshot()
        if snap is not None:
            shots.append(len(snap) / 16000)
    assert 3 <= len(shots) <= 6 and shots == sorted(shots)  # roughly one per 0.8 s of speech, each longer than the last
    assert seg.snapshot() is None


class _Seg:
    def __init__(self, text):
        self.text, self.no_speech_prob, self.avg_logprob = text, 0.0, -0.3


class _Model:
    def __init__(self, text):
        self.text, self.beams = text, []

    def transcribe(self, audio, beam_size=1, **kw):
        self.beams.append(beam_size)
        return [_Seg(self.text)], type("Info", (), {"language": "en"})()


def worker(monkeypatch):
    w = speech.SpeechWorker()
    w.settings = {"speech_lang": "en", "target": "zh-TW", "glossary": "", "auto_proper": True, "keep_katakana": False}
    monkeypatch.setattr(w.translator, "translate", lambda text, *a: "譯:" + text)
    seen = []
    w.partial.connect(lambda said, tr: seen.append(("live", said, tr)))
    w.line.connect(lambda said, tr: seen.append(("final", said, tr)))
    return w, seen


def test_words_are_shown_as_they_are_spoken_then_the_finished_sentence_replaces_them(monkeypatch):
    w, seen = worker(monkeypatch)
    model = _Model("When you are traveling")
    w.live = (w.epoch, voice(2, 0.1))
    w._show_live(model)
    model.text = "When you are traveling to a new country."
    w._handle(model, voice(3, 0.1))
    assert seen == [("live", "When you are traveling", "譯:When you are traveling"),
                    ("final", "When you are traveling to a new country.", "譯:When you are traveling to a new country.")]
    assert model.beams == [1, 2]  # quick for the live line, careful for the finished sentence


def test_a_live_update_for_a_sentence_that_already_ended_is_dropped(monkeypatch):
    w, seen = worker(monkeypatch)
    w.live = (w.epoch, voice(2, 0.1))
    w.epoch += 1  # the sentence finished while the live update was being made
    w._show_live(_Model("old words"))
    assert seen == []
