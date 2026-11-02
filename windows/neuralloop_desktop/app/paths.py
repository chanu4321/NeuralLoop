"""Where NeuralLoop keeps things on this PC, and where its own files are (running from the repo or
installed)."""

import contextlib
import os
import sys
from pathlib import Path

from neuralloop_books import portable

DEVELOPMENT_FOLDER = "NeuralLoop for Windows (development)"


def home() -> Path:
    """%LOCALAPPDATA%\\NeuralLoop on Windows (the pipeline's `portable.app_data`); NEURALLOOP_HOME overrides
    it. Run anywhere else (development on a Mac or Linux), a folder of its own: never the Mac app's library,
    whose progress files this app would otherwise write."""
    override = os.environ.get("NEURALLOOP_HOME")
    if override:
        return Path(override)
    if portable.WINDOWS:
        return portable.app_data()
    return portable.app_data().parent / DEVELOPMENT_FOLDER


def use_own_home() -> None:
    """Pass this app's folder on to every pipeline run it starts (they'd pick the Mac app's on a Mac)."""
    os.environ.setdefault("NEURALLOOP_HOME", str(home()))


def move_old_library() -> bool:
    """Earlier builds kept the library in %APPDATA%\\NeuralLoop (the roaming profile); it moves to
    %LOCALAPPDATA% once, whole, and only when nothing is there yet. True when it moved."""
    if not portable.WINDOWS or os.environ.get("NEURALLOOP_HOME"):
        return False
    old = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming") / portable.WINDOWS_APP_FOLDER
    new = portable.app_data()
    if not old.is_dir() or old.resolve() == new.resolve():
        return False
    if new.exists() and any(new.iterdir()):
        return False
    import shutil

    new.parent.mkdir(parents=True, exist_ok=True)
    with contextlib.suppress(FileNotFoundError):
        new.rmdir()  # an empty folder made by the installer or a first look
    try:
        shutil.move(str(old), str(new))
    except OSError:
        return False
    return True


def books() -> Path:
    path = home() / "books"
    path.mkdir(parents=True, exist_ok=True)
    return path


def ai_config() -> Path:
    return home() / "ai.json"


def frozen() -> bool:
    """Running as the installed app (PyInstaller), not from the repo."""
    return bool(getattr(sys, "frozen", False))


def bundle() -> Path:
    """Where the app's own files are: the PyInstaller folder, or the repo's root in development."""
    if frozen():
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parents[3]


def ui() -> Path:
    return Path(__file__).resolve().parents[1] / "ui"


def pipeline_assets() -> Path:
    """Pip's poses, their animation CSS, and the fonts: the pipeline's own (its explainer videos use them
    too)."""
    import neuralloop_books

    return Path(neuralloop_books.__file__).parent / "assets"


def sounds() -> Path:
    """Silly mode's sounds (the Mac app's .caf files; converted for the window the first time they're
    played)."""
    if frozen():
        return bundle() / "sounds"
    return bundle() / "apple" / "App" / "Resources"


def sample_book() -> Path:
    if frozen():
        return bundle() / "sample" / "sample-book.epub"
    return bundle() / "pipeline" / "sample" / "sample-book.epub"
