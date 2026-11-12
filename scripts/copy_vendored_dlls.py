"""After PyInstaller: copy DLLs that wheels vendor in `<package>.libs` folders and PyInstaller left out.

PyInstaller drops files named like system runtimes (msvcp140-<hash>.dll), but sentencepiece 0.2.3 loads its own copy
from sentencepiece.libs; without it the built app stops at start with "DLL load failed while importing _sentencepiece".
Usage: python scripts/copy_vendored_dlls.py <built app folder>"""
import shutil
import sys
import sysconfig
from pathlib import Path


def copy_missing(app_dir):
    internal = Path(app_dir) / "_internal"
    site = Path(sysconfig.get_paths()["purelib"])
    copied = []
    for libs in site.glob("*.libs"):
        target = internal / libs.name
        if not target.is_dir():
            continue  # that package is not in the build
        for dll in libs.glob("*.dll"):
            if not (target / dll.name).exists():
                shutil.copy2(dll, target / dll.name)
                copied.append(f"{libs.name}/{dll.name}")
    return copied


if __name__ == "__main__":
    for name in copy_missing(sys.argv[1]):
        print("copied", name)
