"""Silly mode's CAF sounds decode to WAV that Edge can play."""

import struct
import wave
from io import BytesIO
from pathlib import Path

import pytest
from neuralloop_desktop.core import caf

SOUNDS = Path(__file__).resolve().parents[2] / "apple" / "App" / "Resources"


def chunk(kind: bytes, body: bytes) -> bytes:
    return struct.pack(">4sq", kind, len(body)) + body


def ima4_file(packets: list[bytes], channels: int = 1, valid: int = 0, priming: int = 0) -> bytes:
    desc = struct.pack(">d4sIIIII", 44100.0, b"ima4", 0, 34 * channels, 64, channels, 0)
    pakt = struct.pack(">qqii", len(packets), valid, priming, 0)
    return (
        b"caff" + struct.pack(">HH", 1, 0) + chunk(b"desc", desc) + chunk(b"pakt", pakt)
        + chunk(b"free", b"\0" * 10) + chunk(b"data", b"\0\0\0\0" + b"".join(packets))
    )  # fmt: skip


def test_packet_steps_follow_ima_rules():
    # predictor 0, step index 0; nibble 4 adds a whole step and moves the index up 2
    samples = caf.packet(b"\x00\x00" + b"\x44" + b"\x00" * 31)
    assert samples[:2] == [7, 17]
    assert len(samples) == 64


def test_negative_predictor_and_sign_bit():
    samples = caf.packet(b"\xff\x80" + b"\x0c" + b"\x00" * 31)  # predictor -128, nibble 12 = minus a step
    assert samples[0] == -128 - 7


def test_stereo_is_interleaved_and_trimmed_to_valid_frames():
    left = b"\x00\x00" + b"\x44" * 32
    right = b"\x00\x00" + b"\xcc" * 32
    rate, channels, samples = caf.decode(ima4_file([left + right], channels=2, valid=10, priming=1))
    assert (rate, channels, len(samples)) == (44100, 2, 20)
    assert samples[0] > 0 > samples[1]


def test_wav_is_readable():
    sound = caf.to_wav(ima4_file([b"\x00\x00" + b"\x44" * 32]))
    with wave.open(BytesIO(sound)) as heard:
        assert (heard.getframerate(), heard.getnchannels(), heard.getsampwidth(), heard.getnframes()) == (
            44100, 1, 2, 64,
        )  # fmt: skip


def test_other_files_are_refused():
    with pytest.raises(caf.NotIMA4):
        caf.decode(b"RIFF....")
    desc = struct.pack(">d4sIIIII", 44100.0, b"lpcm", 0, 4, 1, 2, 16)
    with pytest.raises(caf.NotIMA4):
        caf.decode(b"caff\0\1\0\0" + chunk(b"desc", desc))


@pytest.mark.parametrize("name", ["fahhh", "sad-meow", "sad-violin"])
def test_shipped_sounds_decode(name):
    source = SOUNDS / f"NeuralLoop-{name}.caf"
    if not source.exists():
        pytest.skip("sounds not in this checkout")
    rate, channels, samples = caf.decode(source.read_bytes())
    assert (rate, channels) == (44100, 2)
    assert len(samples) > rate  # over half a second of stereo
    assert max(abs(s) for s in samples) > 1000  # not silence
