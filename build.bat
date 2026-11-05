@echo off
rem Builds the lean PyInstaller folder (run inside the project venv). Use a SHORT output path:
rem Windows path limits break the build in deep folders.
cd /d "%~dp0"
if "%OUT%"=="" set OUT=%~dp0dist
pyinstaller --noconfirm --windowed --icon "%~dp0assets\icon.ico" --name ScreenTranslator --paths src ^
  --distpath "%OUT%" --workpath "%OUT%\work" --specpath "%OUT%" ^
  --add-data "%~dp0src\screen_translator\locales;screen_translator\locales" ^
  --add-data "%~dp0src\screen_translator\icon.png;screen_translator" ^
  --add-data "%~dp0src\screen_translator\tw_words.tsv;screen_translator" ^
  --collect-all ctranslate2 --collect-all sentencepiece --collect-all faster_whisper --collect-all soundcard --collect-all pynput --collect-all llama_cpp --collect-all zhconv --collect-all tokenizers ^
  --exclude-module torch --exclude-module spacy --exclude-module stanza --exclude-module argostranslate --exclude-module av ^
  --exclude-module onnxruntime --exclude-module matplotlib --exclude-module tkinter ^
  --exclude-module PySide6.QtWebEngineCore --exclude-module PySide6.QtWebEngineWidgets ^
  --exclude-module PySide6.QtPdf --exclude-module PySide6.QtQuick --exclude-module PySide6.QtQml ^
  scripts\launch.py
rem Setup installer (needs Inno Setup 6):  ISCC /DSourceDir=%OUT%\ScreenTranslator installer\ScreenTranslator.iss
