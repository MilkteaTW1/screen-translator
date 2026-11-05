"""Everything that differs between Windows and macOS lives here, so the rest of the app is the same on both."""
import os
import re
import subprocess
import sys
from pathlib import Path

IS_WIN = sys.platform == "win32"
IS_MAC = sys.platform == "darwin"

UI_FONT = "Microsoft JhengHei UI" if IS_WIN else "PingFang TC" if IS_MAC else "Noto Sans CJK TC"
INSTALLER_RE = re.compile(r"^ScreenTranslator-Setup-.*\.exe$" if IS_WIN else r"^ScreenTranslator-.*\.dmg$")
WDA_EXCLUDEFROMCAPTURE = 0x11


def data_dir():
    """Where settings, language packs and models live (APPDATA on Windows, Application Support on macOS)."""
    if IS_MAC:
        return Path.home() / "Library" / "Application Support" / "ScreenTranslator"
    return Path(os.environ.get("APPDATA", Path.home())) / "ScreenTranslator"


def _ns_window(widget):
    import objc
    view = objc.objc_object(c_void_p=int(widget.winId()))
    return view.window()


def hide_from_capture(widget, hidden=True):
    """Keep this window out of screenshots and screen recordings (so the app never translates itself)."""
    try:
        if IS_WIN:
            import ctypes
            ctypes.windll.user32.SetWindowDisplayAffinity(int(widget.winId()), WDA_EXCLUDEFROMCAPTURE if hidden else 0)
        elif IS_MAC:
            win = _ns_window(widget)
            if win is not None:
                win.setSharingType_(0 if hidden else 1)  # NSWindowSharingNone / NSWindowSharingReadOnly
    except Exception:
        pass


def show_on_all_spaces(widget):
    """macOS: an overlay stays on every desktop and over full-screen apps."""
    if not IS_MAC:
        return
    try:
        win = _ns_window(widget)
        if win is not None:
            win.setCollectionBehavior_((1 << 0) | (1 << 4) | (1 << 8))  # all spaces | stationary | full-screen auxiliary
            win.setLevel_(25)  # NSStatusWindowLevel: above normal windows
    except Exception:
        pass


def lower_priority():
    """Run below normal priority so translating never competes with what the user is doing."""
    try:
        if IS_WIN:
            import ctypes
            ctypes.windll.kernel32.SetPriorityClass(ctypes.windll.kernel32.GetCurrentProcess(), 0x4000)
        else:
            os.nice(10)
    except Exception:
        pass


def _launch_command():
    if getattr(sys, "frozen", False):
        return [sys.executable, "--minimized"]
    return [sys.executable, "-m", "screen_translator", "--minimized"]


LAUNCH_AGENT = Path.home() / "Library" / "LaunchAgents" / "io.github.milkteatw1.screentranslator.plist"


def set_autostart(on):
    """Start at login (current user, no admin rights): the Run registry key on Windows, a LaunchAgent on macOS."""
    if IS_MAC:
        if on:
            from xml.sax.saxutils import escape
            args = "".join(f"<string>{escape(a)}</string>" for a in _launch_command())
            LAUNCH_AGENT.parent.mkdir(parents=True, exist_ok=True)
            LAUNCH_AGENT.write_text(
                '<?xml version="1.0" encoding="UTF-8"?>\n'
                '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
                f'<plist version="1.0"><dict><key>Label</key><string>{LAUNCH_AGENT.stem}</string>'
                f'<key>ProgramArguments</key><array>{args}</array><key>RunAtLoad</key><true/></dict></plist>\n',
                encoding="utf-8")
        else:
            LAUNCH_AGENT.unlink(missing_ok=True)
        return
    import winreg
    cmd = " ".join(f'"{a}"' if " " in a or i == 0 else a for i, a in enumerate(_launch_command()))
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run", 0,
                        winreg.KEY_SET_VALUE) as k:
        if on:
            winreg.SetValueEx(k, "ScreenTranslator", 0, winreg.REG_SZ, cmd)
        else:
            try:
                winreg.DeleteValue(k, "ScreenTranslator")
            except FileNotFoundError:
                pass


def autostart_is_on():
    if IS_MAC:
        return LAUNCH_AGENT.exists()
    return False


def system_language():
    """The display language of the system, like 'zh-TW' (empty if it cannot be read)."""
    try:
        if IS_WIN:
            import ctypes
            buf = ctypes.create_unicode_buffer(85)
            if ctypes.windll.kernel32.GetUserDefaultLocaleName(buf, len(buf)):
                return buf.value
        elif IS_MAC:
            out = subprocess.run(["defaults", "read", "-g", "AppleLanguages"], capture_output=True, text=True,
                                 timeout=5).stdout
            m = re.search(r'"?([A-Za-z]{2,3}(?:-[A-Za-z0-9]+)*)"?\s*[,)]', out)
            if m:
                tag = m.group(1)  # e.g. zh-Hant-TW, en-US
                if tag.lower().startswith("zh-hant"):
                    return "zh-TW"
                if tag.lower().startswith("zh-hans"):
                    return "zh-CN"
                return tag
    except Exception:
        pass
    return ""


def run_installer(path):
    """Windows: install silently, the installer restarts the app. macOS: open the downloaded disk image."""
    if IS_MAC:
        subprocess.Popen(["open", path])
        return
    subprocess.Popen([path, "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/CLOSEAPPLICATIONS"],
                     creationflags=0x00000008 | 0x00000200, close_fds=True)  # DETACHED_PROCESS | NEW_PROCESS_GROUP
