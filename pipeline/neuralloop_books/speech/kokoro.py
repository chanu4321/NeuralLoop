"""Kokoro-82M (https://huggingface.co/hexgrad/Kokoro-82M) through kokoro-onnx: the local voice on Windows and
Linux, where Rumik (Apple silicon only) can't run. Runs on the CPU with ONNX Runtime.

Model: Apache-2.0. kokoro-onnx: MIT. Its phonemizer and espeak-ng are GPL-3.0 (see NOTICE.md).
The files come from kokoro-onnx's GitHub release and are checked by SHA-256 before they're used.
"""

import contextlib
import hashlib
import os
import re
import urllib.request
import wave
from collections.abc import Callable
from pathlib import Path

from .. import portable
from ..models import SetupError

RATE = 24_000
RELEASE = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/"
# name: (SHA-256, size in bytes)
FILES = {
    "kokoro-v1.0.int8.onnx": ("6e742170d309016e5891a994e1ce1559c702a2ccd0075e67ef7157974f6406cb", 92_361_271),
    "kokoro-v1.0.onnx": ("7d5df8ecf7d4b1878015a32686053fd0eebe2bc377234608764cc0ef3636a6c5", 325_532_387),
    "voices-v1.0.bin": ("bca610b8308e8d99f32e6fe4197e7ec01679264efed0cac9140fe9c29f1fbf7d", 28_214_398),
}
VOICES_FILE = "voices-v1.0.bin"

# The English voices Settings offers: (id, what people see). American/British (a/b), female/male (f/m).
VOICES = (
    ("af_heart", "Heart (warm, American)"),
    ("af_bella", "Bella (bright, American)"),
    ("af_nicole", "Nicole (soft, American)"),
    ("af_sarah", "Sarah (clear, American)"),
    ("am_michael", "Michael (friendly, American)"),
    ("am_adam", "Adam (deep, American)"),
    ("am_puck", "Puck (lively, American)"),
    ("bf_emma", "Emma (British)"),
    ("bf_isabella", "Isabella (British)"),
    ("bm_george", "George (British)"),
    ("bm_fable", "Fable (British)"),
)
VOICE_IDS = tuple(v for v, _ in VOICES)
DEFAULT_VOICES = ("af_heart", "am_michael")
# ai.json made on a Mac (and the shared defaults) names Rumik's voices: keep each host's place.
RUMIK_NAMES = {"Ira": "af_heart", "Aisha": "af_bella", "Siya": "af_nicole", "Zoya": "am_michael"}

_TAGS = re.compile(r"\s*<\s*/?\s*[A-Za-z]+\s*/?\s*>\s*")  # Rumik's <laugh>, <chuckle>, <sigh>


def folder() -> Path:
    return Path(os.environ.get("NEURALLOOP_KOKORO_DIR") or portable.app_data() / "voices" / "kokoro")


def model_file(quality: str, where: Path | None = None) -> Path:
    """ "fast" (default): the 8-bit model, about three times smaller and quicker; "best": full precision."""
    name = "kokoro-v1.0.onnx" if quality == "best" else "kokoro-v1.0.int8.onnx"
    return (where or folder()) / name


def needed(quality: str) -> list[str]:
    return [model_file(quality, Path()).name, VOICES_FILE]


def ready(where: Path, quality: str) -> bool:
    return all(
        (where / name).is_file() and (where / name).stat().st_size == FILES[name][1]
        for name in needed(quality)
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def download(where: Path, names: list[str], progress: Callable[[float], None]) -> None:
    """Fetch what's missing (or damaged) into `where`, checking each file's SHA-256 before keeping it."""
    where.mkdir(parents=True, exist_ok=True)
    todo = []
    for name in names:
        path = where / name
        if path.is_file() and path.stat().st_size == FILES[name][1] and _sha256(path) == FILES[name][0]:
            continue
        todo.append(name)
    total = sum(FILES[name][1] for name in todo) or 1
    got = 0
    for name in todo:
        expected = FILES[name][0]
        partial = where / f"{name}.part"
        digest = hashlib.sha256()
        try:
            with urllib.request.urlopen(RELEASE + name, timeout=60) as response, open(partial, "wb") as out:
                for block in iter(lambda: response.read(1 << 20), b""):
                    out.write(block)
                    digest.update(block)
                    got += len(block)
                    progress(min(got / total, 0.999))
        except OSError as error:
            partial.unlink(missing_ok=True)
            raise SetupError(
                f"Couldn't download Kokoro's voices ({error}). Check the connection and try again."
            ) from None
        if digest.hexdigest() != expected:
            partial.unlink(missing_ok=True)
            raise SetupError(f"The downloaded {name} didn't match the expected file. Try again later.")
        partial.replace(where / name)
    progress(1.0)


def speed_for(delivery: str) -> float:
    """Kokoro has no delivery instructions like Rumik's; a pace word nudges the speed a little."""
    words = delivery.lower()
    if any(w in words for w in ("quick", "fast", "excited", "brisk", "energetic")):
        return 1.08
    if any(w in words for w in ("slow", "calm", "thoughtful", "gentle")):
        return 0.94
    return 1.0


def _voice(name: str) -> str:
    return RUMIK_NAMES.get(name, name)


class KokoroSpeech:
    name = "Kokoro"

    def __init__(self, voices: tuple[str, str] | None, quality: str = "fast"):
        self.voices = tuple(_voice(v) for v in voices) if voices else DEFAULT_VOICES
        self.quality = "best" if quality == "best" else "fast"
        self._model = None

    def check(self) -> None:
        unknown = [v for v in self.voices if v not in VOICE_IDS]
        if unknown:
            raise SetupError(
                f"Kokoro's voices include {', '.join(VOICE_IDS[:4])}…; {', '.join(unknown)} isn't one."
            )
        try:
            import kokoro_onnx  # noqa: F401
        except ImportError as error:
            raise SetupError(
                "Kokoro voices aren't installed yet. Open NeuralLoop once to finish setup."
            ) from error

    def load(self, progress: Callable[[float], None] | None = None):
        if self._model is None:
            from kokoro_onnx import Kokoro

            where = folder()
            if not ready(where, self.quality):
                download(where, needed(self.quality), progress or (lambda _: None))
            self._model = Kokoro(str(model_file(self.quality, where)), str(where / VOICES_FILE))
        return self._model

    def synth(self, text: str, voice: str, delivery: str, path) -> None:
        import numpy as np

        spoken = " ".join(_TAGS.sub(" ", text).split())
        audio = np.zeros(0, dtype=np.float32)
        rate = RATE
        if spoken:
            with contextlib.suppress(ValueError):  # nothing to say once the text is stripped
                audio, rate = self.load().create(
                    spoken, voice=_voice(voice), speed=speed_for(delivery or ""), lang="en-us"
                )
        pcm = (np.clip(np.asarray(audio, dtype=np.float32), -1.0, 1.0) * 32767).astype("<i2")
        with wave.open(str(path), "wb") as out:
            out.setnchannels(1)
            out.setsampwidth(2)
            out.setframerate(rate)
            out.writeframes(pcm.tobytes())
