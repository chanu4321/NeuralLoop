"""Silly mode's sounds ship as the Mac's CAF files (Apple IMA4). Edge can't play those, so they're decoded
to WAV.

Pure: bytes in, bytes out. FFmpeg's CAF reader rejects these files, so this reads them itself: the `desc`,
`pakt`, and `data` chunks, then 34-byte IMA4 packets per channel (a 2-byte header with the predictor and step
index, then 64 four-bit samples, low nibble first).
"""

import struct

STEPS = (
    7, 8, 9, 10, 11, 12, 13, 14, 16, 17, 19, 21, 23, 25, 28, 31, 34, 37, 41, 45, 50, 55, 60, 66, 73,
    80, 88, 97, 107, 118, 130, 143, 157, 173, 190, 209, 230, 253, 279, 307, 337, 371, 408, 449, 494,
    544, 598, 658, 724, 796, 876, 963, 1060, 1166, 1282, 1411, 1552, 1707, 1878, 2066, 2272, 2499,
    2749, 3024, 3327, 3660, 4026, 4428, 4871, 5358, 5894, 6484, 7132, 7845, 8630, 9493, 10442,
    11487, 12635, 13899, 15289, 16818, 18500, 20350, 22385, 24623, 27086, 29794, 32767,
)  # fmt: skip
INDEX = (-1, -1, -1, -1, 2, 4, 6, 8)
PACKET = 34
FRAMES = 64


class NotIMA4(ValueError):
    """The file isn't a CAF holding Apple IMA4 audio."""


def chunks(data: bytes) -> dict[bytes, bytes]:
    """A CAF file's chunks by kind (a size of -1 runs to the end of the file)."""
    if data[:4] != b"caff":
        raise NotIMA4("not a CAF file")
    found: dict[bytes, bytes] = {}
    at = 8
    while at + 12 <= len(data):
        kind, size = struct.unpack(">4sq", data[at : at + 12])
        end = len(data) if size < 0 else at + 12 + size
        found.setdefault(kind, data[at + 12 : end])
        at = end
    return found


def packet(block: bytes) -> list[int]:
    """One channel's 64 samples from its 34-byte packet."""
    header = (block[0] << 8) | block[1]
    sample = header & 0xFF80
    if sample >= 0x8000:
        sample -= 0x10000
    index = min(header & 0x7F, 88)
    out = []
    for byte in block[2:PACKET]:
        for nibble in (byte & 0x0F, byte >> 4):
            step = STEPS[index]
            diff = step >> 3
            if nibble & 4:
                diff += step
            if nibble & 2:
                diff += step >> 1
            if nibble & 1:
                diff += step >> 2
            sample = max(-32768, sample - diff) if nibble & 8 else min(32767, sample + diff)
            index = min(88, max(0, index + INDEX[nibble & 7]))
            out.append(sample)
    return out


def decode(data: bytes) -> tuple[int, int, list[int]]:
    """(sample rate, channels, interleaved 16-bit samples) from an IMA4 CAF file."""
    parts = chunks(data)
    desc = parts.get(b"desc", b"")
    if len(desc) < 32:
        raise NotIMA4("no audio description")
    rate, kind, _flags, per_packet, _frames, channels, _bits = struct.unpack(">d4sIIIII", desc[:32])
    if kind != b"ima4" or channels < 1 or per_packet != PACKET * channels:
        raise NotIMA4(f"{kind.decode('latin-1')} audio, not IMA4")
    audio = parts.get(b"data", b"")[4:]  # the first four bytes are an edit count
    samples: list[int] = []
    for at in range(0, len(audio) - per_packet + 1, per_packet):
        voices = [packet(audio[at + c * PACKET : at + (c + 1) * PACKET]) for c in range(channels)]
        for frame in zip(*voices, strict=True):
            samples.extend(frame)
    pakt = parts.get(b"pakt", b"")
    if len(pakt) >= 24:
        _packets, valid, priming, _remainder = struct.unpack(">qqii", pakt[:24])
        if valid > 0:
            samples = samples[priming * channels : (priming + valid) * channels]
    return int(rate), channels, samples


def wav(rate: int, channels: int, samples: list[int]) -> bytes:
    """A 16-bit PCM WAV file."""
    body = struct.pack(f"<{len(samples)}h", *samples)
    header = struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF", 36 + len(body), b"WAVE",
        b"fmt ", 16, 1, channels, rate, rate * channels * 2, channels * 2, 16,
        b"data", len(body),
    )  # fmt: skip
    return header + body


def to_wav(data: bytes) -> bytes:
    """An IMA4 CAF file as WAV."""
    return wav(*decode(data))
