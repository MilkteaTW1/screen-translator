"""Entry point for the PyInstaller build (the package's __main__ uses relative imports)."""
import sys

from screen_translator.app import main

if "--selftest-speech" in sys.argv:  # used to check a frozen build: transcribe a WAV and print the text
    import wave

    import numpy as np
    from screen_translator import speech
    WhisperModel = speech.whisper_model_class()
    w = wave.open(sys.argv[-1])
    a = np.frombuffer(w.readframes(w.getnframes()), np.int16).astype(np.float32) / 32768
    a = a.reshape(-1, w.getnchannels()).mean(axis=1)
    a = np.interp(np.arange(0, len(a), w.getframerate() / 16000), np.arange(len(a)), a).astype(np.float32)
    model = WhisperModel(str(speech.find_model("small")), device="cpu", compute_type="int8")
    print(" ".join(s.text for s in model.transcribe(a, beam_size=1)[0]))
    import soundcard
    print(soundcard.default_speaker().name)
else:
    main()
