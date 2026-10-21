@echo off
rem Starts Screen Translator without a console window. Create the venv first (see README).
cd /d "%~dp0"
set PYTHONPATH=%~dp0src
if exist ".venv\Scripts\pythonw.exe" (
  start "" ".venv\Scripts\pythonw.exe" -m screen_translator
) else (
  start "" pythonw -m screen_translator
)
