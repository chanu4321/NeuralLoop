"""Pip in the notification area (the Mac's menu bar Pip): open the library or Pip's panel, review cards, pick
up where you left off, pause nudges until tomorrow, or quit. Closing the window keeps Pip here."""

import time
from collections.abc import Callable

from ..core import study
from .notify import icon_png


class Tray:
    def __init__(self, library, actions: dict[str, Callable[..., None]]):
        self.library = library
        self.actions = actions
        self.icon = None

    def _summary(self) -> dict:
        try:
            return study.shelf_summary(self.library.entries(), time.time() * 1000)
        except Exception:
            return {"resume": None, "dueCards": 0}

    def start(self) -> bool:
        try:
            import pystray
            from PIL import Image
        except Exception:
            return False

        def due_text(_item) -> str:
            due = self._summary()["dueCards"]
            return f"Review {due} card{'' if due == 1 else 's'}" if due else "No cards due"

        def resume_text(_item) -> str:
            resume = self._summary()["resume"]
            return f"Continue: {resume['title'][:40]}" if resume else "Nothing to continue yet"

        def has_due(_item) -> bool:
            return bool(self._summary()["dueCards"])

        def has_resume(_item) -> bool:
            return bool(self._summary()["resume"])

        menu = pystray.Menu(
            pystray.MenuItem("Open NeuralLoop", lambda: self.actions["open"](), default=True),
            pystray.MenuItem("Pip's panel", lambda: self.actions["panel"]()),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(resume_text, lambda: self.actions["resume"](), enabled=has_resume),
            pystray.MenuItem(due_text, lambda: self.actions["review"](), enabled=has_due),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Pause nudges until tomorrow", lambda: self.library.pause_until_tomorrow()),
            pystray.MenuItem("Settings", lambda: self.actions["settings"]()),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit NeuralLoop", lambda: self.actions["quit"]()),
        )
        image = Image.open(icon_png()).convert("RGBA").resize((64, 64), Image.LANCZOS)
        self.icon = pystray.Icon("NeuralLoop", image, "NeuralLoop", menu)
        self.icon.run_detached()
        return True

    def notify(self, title: str, body: str) -> None:
        if self.icon is not None:
            self.icon.notify(body, title)

    def stop(self) -> None:
        if self.icon is not None:
            self.icon.stop()
