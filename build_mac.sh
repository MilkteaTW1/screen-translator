#!/bin/bash
# Builds ScreenTranslator.app and a .dmg on macOS (run inside the project venv). Usage: ./build_mac.sh [version]
set -euo pipefail
cd "$(dirname "$0")"
VERSION="${1:-$(grep '^__version__' src/screen_translator/__init__.py | cut -d'"' -f2)}"
OUT="${OUT:-$PWD/dist-mac}"
rm -rf "$OUT" && mkdir -p "$OUT"

# icon.icns from the png
ICONSET="$OUT/icon.iconset"; mkdir -p "$ICONSET"
for s in 16 32 128 256 512; do
  sips -z $s $s assets/icon.png --out "$ICONSET/icon_${s}x${s}.png" >/dev/null
  sips -z $((s*2)) $((s*2)) assets/icon.png --out "$ICONSET/icon_${s}x${s}@2x.png" >/dev/null
done
iconutil -c icns "$ICONSET" -o "$OUT/icon.icns"

pyinstaller --noconfirm --windowed --icon "$OUT/icon.icns" --name ScreenTranslator --paths src \
  --osx-bundle-identifier io.github.milkteatw1.screentranslator \
  --distpath "$OUT" --workpath "$OUT/work" --specpath "$OUT" \
  --add-data "$PWD/src/screen_translator/locales:screen_translator/locales" \
  --add-data "$PWD/src/screen_translator/icon.png:screen_translator" \
  --add-data "$PWD/src/screen_translator/tw_words.tsv:screen_translator" \
  --collect-all ctranslate2 --collect-all sentencepiece --collect-all faster_whisper --collect-all soundcard \
  --collect-all pynput --collect-all zhconv --collect-all tokenizers \
  --hidden-import objc --hidden-import Vision --hidden-import Quartz --hidden-import Foundation \
  --exclude-module torch --exclude-module spacy --exclude-module stanza --exclude-module argostranslate --exclude-module av \
  --exclude-module onnxruntime --exclude-module matplotlib --exclude-module tkinter \
  --exclude-module PySide6.QtWebEngineCore --exclude-module PySide6.QtWebEngineWidgets \
  --exclude-module PySide6.QtPdf --exclude-module PySide6.QtQuick --exclude-module PySide6.QtQml \
  scripts/launch.py

APP="$OUT/ScreenTranslator.app"
PLIST="$APP/Contents/Info.plist"
/usr/libexec/PlistBuddy -c "Add :CFBundleShortVersionString string $VERSION" "$PLIST" 2>/dev/null || \
  /usr/libexec/PlistBuddy -c "Set :CFBundleShortVersionString $VERSION" "$PLIST"
/usr/libexec/PlistBuddy -c "Add :NSMicrophoneUsageDescription string Screen Translator listens to the microphone or to a virtual audio device to translate speech." "$PLIST" || true
/usr/libexec/PlistBuddy -c "Add :NSScreenCaptureUsageDescription string Screen Translator reads the text on your screen to translate it." "$PLIST" || true
# Not notarised: an ad-hoc signature at least makes the bundle valid (Gatekeeper still asks on first open)
codesign --force --deep --sign - "$APP"
codesign --verify --deep --strict "$APP"

STAGE="$OUT/dmg"; mkdir -p "$STAGE"; cp -R "$APP" "$STAGE/"; ln -s /Applications "$STAGE/Applications"
hdiutil create -volname "Screen Translator" -srcfolder "$STAGE" -ov -format UDZO "$OUT/ScreenTranslator-$VERSION.dmg"
echo "Built $OUT/ScreenTranslator-$VERSION.dmg"
