"""Notifications (Notifier.swift) and how a nudge arrives (Nudger.send).

Notifications are Windows toasts (through windows-toasts) that open the book they're about when clicked;
without
that package, the tray icon's own balloon. A silly nudge shows the big Pip with its sound when nothing else
is going
on (`nudges.player`); a test from Settings is always heard.
"""

import contextlib
import threading
from collections.abc import Callable
from pathlib import Path

from neuralloop_books import portable

from ..core import nudges
from . import moment, paths


class Notifier:
    def __init__(
        self,
        settings: Callable[[], dict],
        open_book: Callable[[str], None],
        big_pip: Callable[[dict], bool],
        sound_file: Callable[[str], Path | None],
    ):
        self.settings = settings
        self.open_book = open_book
        self.big_pip = big_pip
        self.sound_file = sound_file
        self.tray_notify: Callable[[str, str], None] | None = None
        self._toaster = None
        self._toasts = None
        if portable.WINDOWS:
            with contextlib.suppress(Exception):  # no WinRT toasts here: the tray balloon carries it
                import windows_toasts

                self._toasts = windows_toasts
                self._toaster = windows_toasts.InteractableWindowsToaster("NeuralLoop")

    def post(
        self, title: str, body: str, book_id: str = "", nudge: dict | None = None, test: bool = False
    ) -> None:
        playing = False
        if nudge and nudge["mood"] != "gentle":
            current = self.settings()
            now = moment.now() if nudges.needs_moment(nudge["mood"], current) else {}
            who = nudges.player(nudge["mood"], current, now, test)
            if who == "bigPip":
                playing = self.big_pip(nudge)
            elif who == "app":
                playing = self.play(nudge["mood"])
        self.toast(title, body, book_id, silent=playing)

    def play(self, mood: str) -> bool:
        """The mood's sound, played by the app itself (a test from Settings with no big Pip)."""
        if not portable.WINDOWS:
            return False
        sound = self.sound_file(mood)
        if not sound:
            return False
        import winsound

        threading.Thread(
            target=winsound.PlaySound, args=(str(sound), winsound.SND_FILENAME), daemon=True
        ).start()
        return True

    def toast(self, title: str, body: str, book_id: str = "", silent: bool = False) -> None:
        if self._toaster is not None:
            try:
                toast = self._toasts.Toast([title, body])
                if silent:
                    toast.audio = self._toasts.ToastAudio(silent=True)
                toast.on_activated = lambda _args: self.open_book(book_id)
                self._toaster.show_toast(toast)
                return
            except Exception:
                pass
        if self.tray_notify:
            with contextlib.suppress(Exception):
                self.tray_notify(title, body)


def icon_png() -> Path:
    """The app icon as a picture (the iPad's 1024 px icon; the installed app carries its own copy)."""
    if paths.frozen():
        return paths.bundle() / "icon.png"
    return (
        paths.bundle() / "apple" / "App" / "iPad" / "Assets.xcassets" / "AppIcon.appiconset" / "icon-1024.png"
    )
