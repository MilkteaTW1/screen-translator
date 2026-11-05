"""System-wide keyboard shortcuts (work while another program has focus): pause/resume, hide translations, pick a region."""
from PySide6.QtCore import QObject, Signal

BINDINGS = {"toggle": "t", "hide": "h", "region": "r"}  # each with Ctrl+Alt held


class Hotkeys(QObject):
    toggle = Signal()
    hide = Signal()
    region = Signal()
    failed = Signal(str)

    def __init__(self):
        super().__init__()
        self._listener = None

    @property
    def running(self):
        return self._listener is not None

    def handlers(self):
        """{letter: function}: each only emits a Qt signal (queued to the GUI thread)."""
        return {BINDINGS["toggle"]: self.toggle.emit, BINDINGS["hide"]: self.hide.emit,
                BINDINGS["region"]: self.region.emit}

    @staticmethod
    def letter(key):
        """The letter of a pynput key, or None. With Ctrl+Alt held Windows gives no character, only the virtual-key
        code (which for letters is the capital's code), so pynput's own hotkey matching never fires."""
        char = getattr(key, "char", None)
        if char and len(char) == 1 and char.isprintable():
            return char.lower()
        vk = getattr(key, "vk", None)
        if vk is not None and 65 <= vk <= 90:
            return chr(vk).lower()
        return None

    def _make_listener(self):
        from pynput import keyboard
        held = set()
        handlers = self.handlers()

        def kind(key):
            name = getattr(key, "name", "")
            return "ctrl" if name.startswith("ctrl") else "alt" if name.startswith("alt") else None

        def on_press(key):
            k = kind(key)
            if k:
                held.add(k)
            elif held >= {"ctrl", "alt"}:
                fn = handlers.get(self.letter(key))
                if fn:
                    fn()

        def on_release(key):
            held.discard(kind(key))

        return keyboard.Listener(on_press=on_press, on_release=on_release)

    def configure(self, on):
        if on and self._listener is None:
            try:
                self._listener = self._make_listener()
                self._listener.daemon = True
                self._listener.start()
            except Exception as e:  # no permission (macOS: Input Monitoring), no display, library missing
                self._listener = None
                self.failed.emit(str(e))
        elif not on and self._listener is not None:
            try:
                self._listener.stop()
            except Exception:
                pass
            self._listener = None
