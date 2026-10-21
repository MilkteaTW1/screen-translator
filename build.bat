@echo off
rem Builds dist\ScreenTranslator with PyInstaller (run inside the project venv).
cd /d "%~dp0"
pyinstaller --noconfirm --windowed --name ScreenTranslator --paths src ^
  --collect-all argostranslate --collect-all stanza --collect-all ctranslate2 --collect-all sentencepiece ^
  --exclude-module PySide6.QtWebEngineCore --exclude-module PySide6.QtWebEngineWidgets ^
  --exclude-module PySide6.QtPdf --exclude-module PySide6.QtQuick --exclude-module PySide6.QtQml ^
  --exclude-module matplotlib --exclude-module tkinter ^
  scripts\launch.py
