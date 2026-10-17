"""Where NeuralLoop keeps things on this PC, and where its own files are (running from the repo or
installed)."""

import os
import sys
from pathlib import Path

from neuralloop_books import portable


def home() -> Path:
    """%APPDATA%\\NeuralLoop on Windows (the pipeline's `portable.app_data`); NEURALLOOP_HOME overrides it."""
    override = os.environ.get("NEURALLOOP_HOME")
    return Path(override) if override else portable.app_data()


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
