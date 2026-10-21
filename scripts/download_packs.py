"""Download Argos offline language packs. Usage: python download_packs.py ja>en en>zt
Each pack is roughly 50-100 MB. Argos codes: zh = Simplified Chinese, zt = Traditional Chinese."""
import sys

import argostranslate.package as package


def main(pairs):
    package.update_package_index()
    available = package.get_available_packages()
    for pair in pairs:
        src, dst = pair.split(">")
        match = next((p for p in available if p.from_code == src and p.to_code == dst), None)
        if match is None:
            print(f"{pair}: no such pack")
            continue
        print(f"{pair}: downloading...")
        package.install_from_path(match.download())
        print(f"{pair}: installed")


if __name__ == "__main__":
    main(sys.argv[1:] or ["--help"])
