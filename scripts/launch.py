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
elif "--selftest-gemma" in sys.argv:  # used to check a frozen build: the llama.cpp library for TranslateGemma loads
    from screen_translator import gemma
    print("gemma library:", gemma.available())
elif "--selftest-ocr" in sys.argv:  # used to check a frozen build: draw a sentence and read it back with the OCR
    from PySide6.QtGui import QColor, QFont, QGuiApplication, QImage, QPainter
    app = QGuiApplication(sys.argv[:1])
    img = QImage(900, 160, QImage.Format_RGB32)
    img.fill(QColor("white"))
    p = QPainter(img)
    p.setPen(QColor("black"))
    p.setFont(QFont("Helvetica", 30))
    p.drawText(30, 90, "Hello world, this is a screen test")
    p.end()
    from screen_translator import ocr
    r = ocr.make_recognizer("en-US")
    print("OCR:", " ".join(l.text for l in r.recognize(bytes(img.constBits())[:900 * 160 * 4], 900, 160)))
else:
    main()
