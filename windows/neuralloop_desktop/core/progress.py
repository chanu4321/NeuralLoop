"""Study progress (progress.json) and merging copies of it without losing anything (Progress.swift).

Progress is a dict in progress.json's own shape: cards ("n:i" to {s, d, reps, last, due}), loop (chapter to
step to time), quiz, recall, remake, mapPos (id to [x, y]), mapSeen, last ({n, stage}), log (day to seconds),
updatedAt, stamps (key to time), watch (chapter to {audio, video} spans), reading (chapter to {pages, count,
last}). Reading it is lenient: one odd entry is skipped, never the rest. Times are Unix milliseconds.
"""

import contextlib
import json
import os
import time
from pathlib import Path
from typing import Any

from . import coverage
from .jsonish import dumps, integer, number

FIELDS = (
    "cards",
    "loop",
    "quiz",
    "recall",
    "remake",
    "mapPos",
    "mapSeen",
    "last",
    "log",
    "updatedAt",
    "stamps",
)


def empty() -> dict:
    return {
        "cards": {},
        "loop": {},
        "quiz": {},
        "recall": {},
        "remake": {},
        "mapPos": {},
        "mapSeen": [],
        "last": None,
        "log": {},
        "updatedAt": 0.0,
        "stamps": {},
        "watch": {},
        "reading": {},
    }


def _plain_number(value: Any) -> float | None:
    return None if isinstance(value, bool) else number(value)


def _card(value: Any) -> dict | None:
    """A card's schedule; one with a missing or odd field is skipped (as the Swift app does)."""
    if not isinstance(value, dict):
        return None
    out = {}
    for key in ("s", "d", "last", "due"):
        n = _plain_number(value.get(key))
        if n is None:
            return None
        out[key] = n
    reps = integer(value.get("reps"))
    if reps is None:
        return None
    out["reps"] = reps
    return out


def _numbers(value: Any) -> dict[str, float]:
    if not isinstance(value, dict):
        return {}
    return {k: n for k, v in value.items() if (n := _plain_number(v)) is not None}


def normalize(raw: Any) -> dict:
    """Lenient decoding: anything odd is skipped on its own."""
    p = empty()
    if not isinstance(raw, dict):
        return p
    if isinstance(raw.get("cards"), dict):
        p["cards"] = {k: c for k, v in raw["cards"].items() if (c := _card(v)) is not None}
    if isinstance(raw.get("loop"), dict):
        for chapter, steps in raw["loop"].items():
            if isinstance(steps, dict):
                p["loop"][chapter] = {k: n for k, v in steps.items() if (n := number(v)) is not None}
    for key in ("quiz", "recall", "remake"):
        if isinstance(raw.get(key), dict):
            p[key] = dict(raw[key])
    if isinstance(raw.get("mapPos"), dict):
        p["mapPos"] = {
            k: [float(v[0]), float(v[1])]
            for k, v in raw["mapPos"].items()
            if isinstance(v, list) and len(v) == 2 and all(_plain_number(x) is not None for x in v)
        }
    if isinstance(raw.get("mapSeen"), list):
        p["mapSeen"] = sorted({i for v in raw["mapSeen"] if (i := integer(v)) is not None})
    last = raw.get("last")
    if isinstance(last, dict) and integer(last.get("n")) is not None and isinstance(last.get("stage"), str):
        p["last"] = {"n": integer(last["n"]), "stage": last["stage"]}
    p["log"] = _numbers(raw.get("log"))
    p["updatedAt"] = _plain_number(raw.get("updatedAt")) or 0.0
    p["stamps"] = _numbers(raw.get("stamps"))
    if isinstance(raw.get("watch"), dict):
        p["watch"] = {k: coverage.watch(v) for k, v in raw["watch"].items() if k.lstrip("-").isdigit()}
    if isinstance(raw.get("reading"), dict):
        p["reading"] = {
            k: coverage.reading_record(v)
            for k, v in raw["reading"].items()
            if k.lstrip("-").isdigit() and isinstance(v, dict)
        }
    return p


def encode(p: dict) -> bytes:
    """Watching and reading are left out while empty (files from before them stay the same); keys sorted."""
    out = {k: p[k] for k in FIELDS if not (k == "last" and p["last"] is None)}
    out["watch"] = {k: coverage.encode_watch(v) for k, v in p["watch"].items()}
    out["reading"] = {k: coverage.encode_reading(v) for k, v in p["reading"].items()}
    for key in ("watch", "reading"):
        if not out[key]:
            del out[key]
    return dumps(out)


# Changes that carry their own time, so merging knows what's newest.


def _stamp(p: dict, key: str, now: float) -> None:
    p["stamps"][key] = max(p["stamps"].get(key, 0.0), now)
    p["updatedAt"] = max(p["updatedAt"], now)


def set_quiz(p: dict, key: str, value: Any, now: float) -> None:
    p["quiz"][key] = value
    _stamp(p, f"quiz.{key}", now)


def set_recall(p: dict, key: str, value: Any, now: float) -> None:
    p["recall"][key] = value
    _stamp(p, f"recall.{key}", now)


def set_remake(p: dict, key: str, value: Any, now: float) -> None:
    p["remake"][key] = value
    _stamp(p, f"remake.{key}", now)


def set_map_pos(p: dict, node: str, point: list[float], now: float) -> None:
    p["mapPos"][node] = [float(point[0]), float(point[1])]
    _stamp(p, f"mapPos.{node}", now)


def set_last(p: dict, n: int, stage: str, now: float) -> None:
    p["last"] = {"n": n, "stage": stage}
    _stamp(p, "last", now)


def merged(devices: list[dict]) -> dict:
    """Every device's progress in one.

    Cards: the latest review wins. Loop steps: done anywhere is done (earliest time). Watching: union.
    Reading: most seconds per page, furthest page. Study log: summed (each device's file holds only its own
    time). Quiz, recall, remake, map positions, where you left off: newest stamp wins (a tie goes to the most
    recently updated device).
    """
    out = empty()
    ordered = sorted(devices, key=lambda d: (d["updatedAt"], len(d["stamps"])))
    for device in ordered:
        for cid, card in device["cards"].items():
            if card["last"] >= out["cards"].get(cid, {"last": -1})["last"]:
                out["cards"][cid] = dict(card)
        for chapter, steps in device["loop"].items():
            mine = out["loop"].setdefault(chapter, {})
            for step, at in steps.items():
                mine[step] = min(mine[step], at) if step in mine else at
        for day, seconds in device["log"].items():
            out["log"][day] = out["log"].get(day, 0.0) + seconds
        for chapter, w in device["watch"].items():
            out["watch"][chapter] = (
                coverage.watch_union(out["watch"][chapter], w) if chapter in out["watch"] else w
            )
        for chapter, r in device["reading"].items():
            here = out["reading"].get(chapter)
            out["reading"][chapter] = coverage.reading_merged(here, r) if here else r
        for field in ("quiz", "recall", "remake", "mapPos"):
            for key, value in device[field].items():
                if device["stamps"].get(f"{field}.{key}", 0.0) >= out["stamps"].get(f"{field}.{key}", 0.0):
                    out[field][key] = value
        out["mapSeen"] = sorted(set(out["mapSeen"]) | set(device["mapSeen"]))
        if device["last"] is not None and device["stamps"].get("last", 0.0) >= out["stamps"].get("last", 0.0):
            out["last"] = dict(device["last"])
        for key, at in device["stamps"].items():
            out["stamps"][key] = max(out["stamps"].get(key, at), at)
        out["updatedAt"] = max(out["updatedAt"], device["updatedAt"])
    return out


def merged_same_device(a: dict, b: dict) -> dict:
    """Two copies of this device's own file: like devices, but each day keeps the larger study time."""
    out = merged([a, b])
    days = a["log"].keys() | b["log"].keys()
    out["log"] = {day: max(a["log"].get(day, 0.0), b["log"].get(day, 0.0)) for day in days}
    return out


# progress.json on disk.


def load(folder: Path, now: float | None = None) -> dict:
    """No file is a fresh start; one that isn't JSON is kept aside (progress.json.unreadable-<time>)."""
    path = folder / "progress.json"
    try:
        data = path.read_bytes()
    except OSError:
        return empty()
    try:
        return normalize(json.loads(data))
    except ValueError:
        stamp = int(now if now is not None else time.time())
        with contextlib.suppress(OSError):
            path.replace(folder / f"progress.json.unreadable-{stamp}")
        return empty()


def others(folder: Path) -> list[dict]:
    """Other devices' progress for this book (devices/<id>.json), when a library came from a Mac with sync."""
    found = []
    with contextlib.suppress(OSError):
        for path in sorted((folder / "devices").glob("*.json")):
            with contextlib.suppress(OSError, ValueError):
                found.append(normalize(json.loads(path.read_bytes())))
    return found


def load_merged(folder: Path) -> tuple[dict, dict]:
    """(this device's own progress, the view with every other device's merged in)."""
    own = load(folder)
    rest = others(folder)
    return own, merged([own, *rest]) if rest else own


def save(p: dict, folder: Path, own_log: dict | None = None) -> None:
    """Writes this device's file atomically, with only its own study time when `own_log` is given."""
    mine = dict(p)
    if own_log is not None:
        mine["log"] = dict(own_log)
    tmp = folder / "progress.json.tmp"
    tmp.write_bytes(encode(mine))
    os.replace(tmp, folder / "progress.json")
