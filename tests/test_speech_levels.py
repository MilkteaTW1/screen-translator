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
    assert 2.4 / speech.PARTIAL_STEP <= len(shots) <= 6 / speech.PARTIAL_STEP and shots == sorted(shots)  # about one per step of speech, each longer than the last
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
    w.running = True
    w.settings = {"speech_lang": "en", "target": "zh-TW", "glossary": "", "auto_proper": True, "keep_katakana": False}
    monkeypatch.setattr(w.translator, "translate", lambda text, *a: "譯:" + text)
    seen = []
    w.partial.connect(lambda said, tr: seen.append(("live", said, tr)))
    w.line.connect(lambda said, tr: seen.append(("final", said, tr)))
    return w, seen


def drain(w):
    """Runs the translation thread until what is waiting for it has been translated."""
    import threading, time
    t = threading.Thread(target=w._translate_loop, args=(w.gen,), daemon=True)
    t.start()
    deadline = time.time() + 5
    while time.time() < deadline and (not w.finals.empty() or w._live_job is not None):
        time.sleep(0.02)
    time.sleep(0.2)
    w.running = False
    t.join(2)
    w.running = True
    from PySide6.QtCore import QCoreApplication
    from PySide6.QtWidgets import QApplication; QApplication.instance() or QApplication([])
    QCoreApplication.processEvents()  # signals sent from the thread are delivered by the event loop


def test_words_are_shown_as_they_are_spoken_then_the_finished_sentence_replaces_them(monkeypatch):
    w, seen = worker(monkeypatch)
    model = _Model("When you are traveling")
    w.live = (w.epoch, voice(2, 0.1))
    w._show_live(model, w.gen)
    model.text = "When you are traveling to a new country."
    ended = w.epoch
    w.epoch += 1  # the sentence is over
    w._handle(model, ended, voice(3, 0.1), w.gen)  # it ended long after the live reading: read again
    drain(w)
    assert seen[0] == ("live", "When you are traveling", "")  # the words come first, at once
    assert seen[-1] == ("final", "When you are traveling to a new country.", "譯:When you are traveling to a new country.")
    assert model.beams == [1, 1]


def test_a_finished_sentence_that_the_live_reading_already_heard_is_not_read_again(monkeypatch):
    w, seen = worker(monkeypatch)
    model = _Model("When you are traveling")
    audio = voice(2, 0.1)
    w.live = (w.epoch, audio)
    w._show_live(model, w.gen)
    ended = w.epoch
    w.epoch += 1
    w._handle(model, ended, audio, w.gen)
    drain(w)
    assert model.beams == [1]  # only the live reading
    assert seen[-1] == ("final", "When you are traveling", "譯:When you are traveling")


def test_the_translation_of_the_sentence_being_spoken_shows_while_it_is_still_said(monkeypatch):
    w, seen = worker(monkeypatch)
    w.live = (w.epoch, voice(2, 0.1))
    w._show_live(_Model("When you are traveling"), w.gen)
    drain(w)
    assert ("live", "When you are traveling", "譯:When you are traveling") in seen


def test_a_live_update_for_a_sentence_that_already_ended_is_dropped(monkeypatch):
    w, seen = worker(monkeypatch)
    w.live = (w.epoch, voice(2, 0.1))
    w.epoch += 1  # the sentence finished while the live update was being made
    w._show_live(_Model("old words"), w.gen)
    assert seen == []


def test_nothing_is_shown_after_speech_was_stopped(monkeypatch):
    w, seen = worker(monkeypatch)
    model = _Model("When you are traveling")
    gen = w.gen
    w.live = (w.epoch, voice(2, 0.1))
    w.running = False  # stopped while the sentence was being read
    w._show_live(model, gen)
    w._handle(model, w.epoch, voice(3, 0.1), gen)
    assert seen == []


def test_what_was_heard_before_a_stop_is_gone_after_the_next_start(monkeypatch):
    w, seen = worker(monkeypatch)
    w.audio.put(voice(1, 0.1))
    w.utterances.put((0, voice(2, 0.1)))
    w.finals.put(("old", "en"))
    w.epoch = 5
    w.stop()
    old = w.gen
    monkeypatch.setattr(w, "_capture", lambda gen: None)
    monkeypatch.setattr(w, "_segment", lambda gen: None)
    monkeypatch.setattr(w, "_transcribe", lambda gen: None)
    monkeypatch.setattr(w, "_translate_loop", lambda gen: None)
    w.start()
    assert w.gen > old and w.epoch == 0
    assert w.audio.empty() and w.utterances.empty() and w.finals.empty()
    assert not w._alive(old)  # threads of the earlier run end


def test_the_sentence_being_spoken_is_not_sent_for_translation_with_every_new_word(monkeypatch):
    w, seen = worker(monkeypatch)
    sent = []
    monkeypatch.setattr(w.translator, "translate", lambda text, *a: sent.append(text) or "譯:" + text)
    for text in ("When", "When you", "When you are", "When you are traveling"):
        w.live = (w.epoch, voice(2, 0.1))
        w._show_live(_Model(text), w.gen)
    drain(w)
    assert len(sent) == 1  # one request, not four
    assert [s[1] for s in seen if s[0] == "live"][:4] == ["When", "When you", "When you are", "When you are traveling"]  # the words still follow


def test_a_caption_line_that_nothing_replaces_goes_away_too():
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    from screen_translator.overlay import CaptionOverlay
    app = QApplication.instance() or QApplication([])
    c = CaptionOverlay(app.primaryScreen())
    c.set_live("half a sentence", "")
    c.live_at -= c.LIFETIME + 1  # speech stopped mid-sentence long ago
    c._expire()
    assert c.live is None


def test_words_already_in_the_target_script_are_not_translated():
    from screen_translator.speech import _OWN_RE, foreign_runs, mix_translate
    zh = _OWN_RE["zh"]
    assert foreign_runs("我今天去公司", zh) == []
    assert mix_translate("我今天去公司", zh, lambda p: 1 / 0) == ""  # nothing is asked of the translator
    text = "我用 Python 寫程式"
    (a, b), = foreign_runs(text, zh)
    assert text[a:b] == "Python"


def test_a_run_of_foreign_words_is_translated_as_one_and_put_back():
    from screen_translator.speech import _OWN_RE, mix_translate
    asked = []
    out = mix_translate("我覺得 this is really good 而且很便宜", _OWN_RE["zh"], lambda p: asked.append(p) or "這真的很好")
    assert asked == ["this is really good"] and out == "我覺得 這真的很好 而且很便宜"
    assert mix_translate("我覺得 hello 很好", _OWN_RE["zh"], lambda p: "") == "我覺得 hello 很好"  # no translation: as said


def _speech_with(target, translate):
    from screen_translator import speech
    cls = next(v for v in vars(speech).values() if isinstance(v, type) and "_translate" in vars(v))
    obj = cls.__new__(cls)
    obj.settings = {"target": target, "glossary": "", "auto_proper": False, "keep_katakana": False}
    obj.translator = type("T", (), {"translate": staticmethod(translate), "missing_packs": set(),
                                    "offline_error": None, "google_error": None})()
    obj.status = type("S", (), {"emit": staticmethod(lambda *_: None)})()
    return obj


def test_chinese_speech_is_shown_as_it_is_and_never_sent_to_the_translator():
    def never(*a, **k):
        raise AssertionError("asked")
    s = _speech_with("zh-TW", never)
    assert s._translate("我今天去公司", "zh") == ""
    assert s._translate("我今天去公司", "en") == ""  # the language guess was wrong: still no translation


def test_english_words_inside_chinese_speech_are_translated_alone():
    seen = []
    s = _speech_with("zh-TW", lambda text, *a, **k: seen.append(text) or "很好")
    assert s._translate("我覺得 very good 啊", "zh") == "我覺得很好啊"
    assert seen == ["very good"]
    assert _speech_with("zh-TW", lambda text, *a, **k: "你好嗎")._translate("how are you", "en") == "你好嗎"


def test_streaming_models_are_chosen_by_the_spoken_language():
    from screen_translator import streaming
    assert streaming.key_for("auto") == "multi" and streaming.key_for("zh") == "zh-en"
    assert streaming.key_for("en") == "en" and streaming.key_for("ko") == "ko" and streaming.key_for("ja") == "multi"
    assert streaming.key_for("fr") is None  # only Whisper reads it


def test_streaming_text_is_written_like_a_sentence_and_the_language_guessed():
    from screen_translator import streaming
    assert streaming.tidy("WHEN I ARRIVE IN TOKYO") == "When I arrive in tokyo"
    assert streaming.tidy("你好 WORLD") == "你好 world"  # the English in it is not shouted
    assert streaming.guess_language("你好嗎", "auto") == "zh" and streaming.guess_language("hello", "auto") == "en"
    assert streaming.guess_language("hello", "ja") == "ja"
    assert streaming.guess_language("こんにちは", "auto") == "ja" and streaming.guess_language("привет", "auto") == "ru"
    assert streaming.guess_language("xin chào bạn", "auto") == "vi" and streaming.guess_language("สวัสดี", "auto") == "th"


def test_fast_captions_show_words_at_once_and_end_with_a_translated_line(monkeypatch):
    from screen_translator import streaming
    w, seen = worker(monkeypatch)
    w.settings["speech_lang"] = "en"

    class Fake:  # a recogniser: the words grow, then the sentence ends
        script = iter([("Hello", False), ("Hello there", False), ("Hello there my friend", True)])

        def __init__(self, key):
            pass

        def feed(self, chunk):
            return next(Fake.script)

    monkeypatch.setattr(streaming, "Stream", Fake)
    for _ in range(3):
        w.audio.put(voice(1, 0.1)[:1600])
    import threading, time
    gen = w.gen
    th = threading.Thread(target=w._stream, args=(gen, "en"), daemon=True)
    th.start()
    time.sleep(0.5)
    drain(w)
    w.running = False
    th.join(2)
    words = [s[1] for s in seen if s[0] == "live"]
    assert words[:2] == ["Hello", "Hello there"]
    assert seen[-1] == ("final", "Hello there my friend", "譯:Hello there my friend")


def test_auto_starts_on_the_fast_captions_and_moves_to_whisper_when_another_language_is_heard(monkeypatch):
    from screen_translator import streaming
    w, _seen = worker(monkeypatch)
    monkeypatch.setattr(streaming, "find", lambda key: "folder")  # every streaming model is downloaded
    w.settings["speech_fast"] = True
    w.settings["speech_lang"] = "auto"
    assert w.stream_key() == "multi"  # words at once, in eight languages
    monkeypatch.setattr(streaming, "find", lambda key: "folder" if key == "zh-en" else None)  # only the older model is there
    assert w.stream_key() == "zh-en"
    monkeypatch.setattr(streaming, "find", lambda key: "folder")
    w.lang_now = "whisper"  # what _move_to sets when French is heard: no streaming model for it
    assert w.stream_key() is None
    w.lang_now = "ja"
    assert w.stream_key() == "multi"
    w.lang_now = None
    w.settings["speech_lang"] = "fr"
    assert w.stream_key() is None  # no streaming model for French: Whisper
    w.settings["speech_fast"] = False
    w.settings["speech_lang"] = "en"
    assert w.stream_key() is None  # fast mode off


def test_auto_language_watch_moves_on_only_for_a_clear_other_language():
    from screen_translator.streaming import AutoLanguage
    w = AutoLanguage()
    assert w.add("en", 0.99) is None and w.add("zh", 0.9) is None and w.add("yue", 0.9) is None
    assert w.add("ja", 0.99) is None and w.add("ru", 0.99) is None  # the auto model reads them already
    assert w.add("fr", 0.4) is None  # too unsure
    assert w.add("fr", 0.7) is None  # once and not sure: wait
    assert w.add("fr", 0.7) == "fr"  # twice in a row
    w = AutoLanguage()
    assert w.add("ko", 0.95) == "ko"  # once but very sure
    w = AutoLanguage()
    assert w.add("fr", 0.7) is None and w.add("en", 0.9) is None and w.add("fr", 0.7) is None  # English in between: start over


def test_auto_language_watch_checks_the_first_sentences_then_one_in_four():
    from screen_translator.streaming import AutoLanguage
    w = AutoLanguage()
    due = [w.due() for _ in range(12)]
    assert due[:3] == [True, True, True] and due[3:8] == [True, False, False, False, True] and sum(due) == 6
