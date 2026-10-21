"""Download Argos offline language packs. Usage: python scripts/download_packs.py ja>en en>zt
Each pack is roughly 50-100 MB. Argos codes: zh = Simplified Chinese, zt = Traditional Chinese.
(The app also offers to download missing packs when you pick a language.)"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from screen_translator.translator import install_pack  # noqa: E402


def main(pairs):
    for pair in pairs:
        src, dst = pair.split(">")
        print(f"{pair}: downloading...")
        try:
            install_pack(src, dst)
            print(f"{pair}: installed")
        except Exception as e:
            print(f"{pair}: {e}")


if __name__ == "__main__":
    main(sys.argv[1:])
