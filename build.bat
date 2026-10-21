@echo off
rem Builds dist\ScreenTranslator with PyInstaller (run inside the project venv).
cd /d "%~dp0"
pyinstaller --noconfirm --windowed --name ScreenTranslator --paths src ^
  --collect-all argostranslate --collect-all stanza --collect-all ctranslate2 ^
  src\screen_translator\__main__.py
