"""Kokoro: the local voice on Windows and Linux (Rumik needs Apple silicon)."""

import hashlib
import io
import sys
import types
import wave
from typing import ClassVar

import pytest

from neuralloop_books.models import SetupError
from neuralloop_books.speech import kokoro
from neuralloop_books.speech.kokoro import KokoroSpeech


class FakeKokoro:
    made: ClassVar[list] = []

    def __init__(self, model_path, voices_path):
        self.paths = (model_path, voices_path)
        FakeKokoro.made.append(self)
        self.said: list[tuple[str, str, float]] = []

    def create(self, text, voice, speed=1.0, lang="en-us"):
        import numpy as np

        self.said.append((text, voice, speed))
        return np.full(2400, 0.5, dtype=np.float32), 24_000


@pytest.fixture
def fake_kokoro(monkeypatch, tmp_path):
    module = types.ModuleType("kokoro_onnx")
    module.Kokoro = FakeKokoro
    monkeypatch.setitem(sys.modules, "kokoro_onnx", module)
    monkeypatch.setenv("NEURALLOOP_KOKORO_DIR", str(tmp_path / "kokoro"))
    FakeKokoro.made = []
    return module


def test_default_voices_are_a_warm_pair():
    assert KokoroSpeech(None).voices == ("af_heart", "am_michael")


def test_the_macs_rumik_voices_become_kokoros_pair():
    """ai.json written on a Mac (or the defaults) names Rumik's voices; Kokoro keeps the same host order."""
    assert KokoroSpeech(("Ira", "Zoya")).voices == ("af_heart", "am_michael")
    assert KokoroSpeech(("Zoya", "af_bella")).voices == ("am_michael", "af_bella")


def test_unknown_voices_are_refused(fake_kokoro):
    with pytest.raises(SetupError, match="af_heart"):
        KokoroSpeech(("Samantha", "Daniel")).check()


def test_check_needs_the_package(monkeypatch):
    monkeypatch.setitem(sys.modules, "kokoro_onnx", None)
    with pytest.raises(SetupError, match="finish setup"):
        KokoroSpeech(None).check()


def test_quality_picks_the_model_file():
    assert kokoro.model_file("fast").name == "kokoro-v1.0.int8.onnx"
    assert kokoro.model_file("best").name == "kokoro-v1.0.onnx"
    assert set(kokoro.FILES) == {"kokoro-v1.0.int8.onnx", "kokoro-v1.0.onnx", "voices-v1.0.bin"}


def fake_download(contents: dict[str, bytes]):
    def opener(url, timeout=None):
        return _Response(contents[url.rsplit("/", 1)[-1]])

    return opener


class _Response(io.BytesIO):
    def __init__(self, data: bytes):
        super().__init__(data)
        self.headers = {"Content-Length": str(len(data))}

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def test_download_checks_every_file(tmp_path, monkeypatch):
    blobs = {"kokoro-v1.0.int8.onnx": b"model", "voices-v1.0.bin": b"voices"}
    monkeypatch.setattr(
        kokoro, "FILES", {name: (hashlib.sha256(data).hexdigest(), len(data)) for name, data in blobs.items()}
    )
    monkeypatch.setattr(kokoro.urllib.request, "urlopen", fake_download(blobs))
    seen: list[float] = []
    kokoro.download(tmp_path, ["kokoro-v1.0.int8.onnx", "voices-v1.0.bin"], seen.append)
    assert (tmp_path / "voices-v1.0.bin").read_bytes() == b"voices"
    assert seen and seen[-1] == 1.0
    kokoro.download(tmp_path, ["voices-v1.0.bin"], seen.append)  # already there: nothing to fetch


def test_download_refuses_a_file_that_doesnt_match(tmp_path, monkeypatch):
    monkeypatch.setattr(kokoro, "FILES", {"voices-v1.0.bin": ("0" * 64, 6)})
    monkeypatch.setattr(kokoro.urllib.request, "urlopen", fake_download({"voices-v1.0.bin": b"evil!!"}))
    with pytest.raises(SetupError, match="didn't match"):
        kokoro.download(tmp_path, ["voices-v1.0.bin"], lambda _: None)
    assert list(tmp_path.iterdir()) == []


def test_a_file_already_there_but_damaged_is_fetched_again(tmp_path, monkeypatch):
    good = b"voices"
    monkeypatch.setattr(kokoro, "FILES", {"voices-v1.0.bin": (hashlib.sha256(good).hexdigest(), len(good))})
    monkeypatch.setattr(kokoro.urllib.request, "urlopen", fake_download({"voices-v1.0.bin": good}))
    (tmp_path / "voices-v1.0.bin").write_bytes(b"halfdo")  # same size, wrong bytes
    kokoro.download(tmp_path, ["voices-v1.0.bin"], lambda _: None)
    assert (tmp_path / "voices-v1.0.bin").read_bytes() == good


def test_synth_writes_a_16_bit_wav_and_drops_rumik_tags(fake_kokoro, tmp_path, monkeypatch):
    monkeypatch.setattr(kokoro, "ready", lambda folder, quality: True)
    voice = KokoroSpeech(None)
    voice.synth("Well <laugh> that's caching!", "af_heart", "happy, steady pace", tmp_path / "x.wav")
    assert FakeKokoro.made[0].said == [("Well that's caching!", "af_heart", 1.0)]
    with wave.open(str(tmp_path / "x.wav")) as out:
        assert (out.getnchannels(), out.getsampwidth(), out.getframerate(), out.getnframes()) == (
            1,
            2,
            24000,
            2400,
        )


def test_the_model_is_loaded_once(fake_kokoro, tmp_path, monkeypatch):
    monkeypatch.setattr(kokoro, "ready", lambda folder, quality: True)
    voice = KokoroSpeech(None, quality="best")
    voice.synth("one", "af_heart", "", tmp_path / "a.wav")
    voice.synth("two", "am_michael", "", tmp_path / "b.wav")
    assert len(FakeKokoro.made) == 1
    assert FakeKokoro.made[0].paths[0].endswith("kokoro-v1.0.onnx")


def test_a_brisk_delivery_speaks_a_little_faster():
    assert kokoro.speed_for("excited, quick pace") > 1.0
    assert kokoro.speed_for("calm, slow and thoughtful") < 1.0
    assert kokoro.speed_for("warm, steady pace") == 1.0
