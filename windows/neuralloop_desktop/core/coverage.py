"""What has really been played and read (PlayCoverage.swift, ReadingCredit.swift; spec 09).

Played media is a union of [start, end] stretches of media time that played at a believable speed (seeks,
scrubbing, faster than 2x and replays add nothing). Reading credits seconds to the pages on screen while
someone is there; a page is read once it has had max(6 s, its words at 600 a minute); Read is done at 85% of
pages with the last reached."""

import math
from typing import Any

from .jsonish import integer, number, tenth

FASTEST_RATE = 2.0
SLACK = 0.75
LISTENING_ENOUGH = 0.85


def _finite(*values: float) -> bool:
    return all(isinstance(v, (int, float)) and math.isfinite(v) for v in values)


def insert(spans: list[list[float]], start: float, end: float) -> list[list[float]]:
    """`spans` with [start, end] added as a union (sorted, non-overlapping)."""
    if not _finite(start, end) or end <= start:
        return spans
    lo, hi = start, end
    kept = []
    for a, b in spans:
        if b < lo or a > hi:
            kept.append([a, b])
        else:
            lo, hi = min(lo, a), max(hi, b)
    kept.append([lo, hi])
    return sorted(kept, key=lambda s: s[0])


def spans(raw: Any) -> list[list[float]]:
    out: list[list[float]] = []
    for span in raw if isinstance(raw, list) else []:
        if isinstance(span, list) and len(span) == 2:
            a, b = number(span[0]), number(span[1])
            if a is not None and b is not None and not isinstance(span[0], bool):
                out = insert(out, a, b)
    return out


def add(
    cover: list[list[float]], start: float, end: float, rate: float, wall: float
) -> tuple[list[list[float]], bool]:
    """One reported stretch of playback; counts only forwards, at most 2x, and no further than the rate
    allows.
    """
    if not _finite(start, end, rate, wall) or wall <= 0 or rate <= 0 or rate > FASTEST_RATE + 1e-6:
        return cover, False
    advance = end - start
    if advance <= 0 or advance > rate * wall + SLACK or advance > FASTEST_RATE * wall + SLACK:
        return cover, False
    return insert(cover, max(0.0, start), end), True


def union(a: list[list[float]], b: list[list[float]]) -> list[list[float]]:
    out = [list(s) for s in a]
    for s, e in b:
        out = insert(out, s, e)
    return out


def seconds_within(cover: list[list[float]], duration: float) -> float:
    if duration <= 0:
        return 0.0
    return sum(max(0.0, min(e, duration) - max(s, 0.0)) for s, e in cover)


def fraction(cover: list[list[float]], duration: float | None) -> float:
    if not duration or duration <= 0:
        return 0.0
    return min(1.0, seconds_within(cover, duration) / duration)


def watch(raw: Any) -> dict:
    raw = raw if isinstance(raw, dict) else {}
    return {"audio": spans(raw.get("audio")), "video": spans(raw.get("video"))}


def watch_union(a: dict, b: dict) -> dict:
    return {"audio": union(a["audio"], b["audio"]), "video": union(a["video"], b["video"])}


def encode_watch(w: dict) -> dict:
    return {k: [[tenth(s), tenth(e)] for s, e in w[k]] for k in ("audio", "video")}


def listening_share(w: dict | None, audio_length: float | None, video_length: float | None) -> float:
    if not w:
        return 0.0
    return max(fraction(w["audio"], audio_length), fraction(w["video"], video_length))


def listening_done(w: dict | None, audio_length: float | None, video_length: float | None) -> bool:
    return listening_share(w, audio_length, video_length) >= LISTENING_ENOUGH - 1e-9


# Reading.

IDLE_LIMIT = 90.0
MINIMUM_SECONDS = 6.0
FASTEST_WPM = 600.0
READING_ENOUGH = 0.85
SECTION_WORDS = 300
LONGEST_TICK = 2.0


def reading_record(raw: Any) -> dict:
    raw = raw if isinstance(raw, dict) else {}
    pages = raw.get("pages") if isinstance(raw.get("pages"), dict) else {}
    clean = {
        k: n for k, v in pages.items() if (n := number(v)) is not None and not isinstance(v, bool) and n >= 0
    }
    count = integer(raw.get("count"))
    last = integer(raw.get("last"))
    return {"pages": clean, "count": max(0, count or 0), "last": last}


def encode_reading(r: dict) -> dict:
    out = {"pages": {k: tenth(v) for k, v in r["pages"].items()}, "count": r["count"]}
    if r.get("last") is not None:
        out["last"] = r["last"]
    return out


def reading_merged(a: dict, b: dict) -> dict:
    pages = dict(a["pages"])
    for k, v in b["pages"].items():
        pages[k] = max(pages.get(k, v), v)
    lasts = [x for x in (a.get("last"), b.get("last")) if x is not None]
    return {"pages": pages, "count": max(a["count"], b["count"]), "last": max(lasts) if lasts else None}


def needed(words: int) -> float:
    return max(MINIMUM_SECONDS, max(0, words) / FASTEST_WPM * 60)


def earning(now: float, last_input: float | None, app_active: bool, window_visible: bool) -> bool:
    return app_active and window_visible and last_input is not None and now - last_input <= IDLE_LIMIT


def credit(record: dict, visible: list[int], seconds: float, page_count: int, is_earning: bool) -> bool:
    """One tick shared between the pages on screen. Returns whether anything was credited."""
    pages = {p for p in visible if isinstance(p, int) and 0 <= p < page_count}
    if not is_earning or not pages or not _finite(seconds) or seconds <= 0:
        return False
    share = min(seconds, LONGEST_TICK) / len(pages)
    for page in pages:
        record["pages"][str(page)] = record["pages"].get(str(page), 0.0) + share
    record["count"] = page_count
    record["last"] = max(record.get("last") or 0, max(pages))
    return True


def reading_progress(record: dict | None, needs: list[float]) -> dict:
    pages = (record or {}).get("pages", {})
    counted = sum(1 for i, need in enumerate(needs) if pages.get(str(i), 0.0) >= need - 1e-9)
    last = (record or {}).get("last")
    reached = bool(needs) and (last if last is not None else -1) >= len(needs) - 1
    total = len(needs)
    frac = counted / total if total else 0.0
    return {
        "counted": counted,
        "total": total,
        "reachedLast": reached,
        "fraction": frac,
        "done": total > 0 and reached and frac >= READING_ENOUGH - 1e-9,
    }


def words(block: str) -> int:
    """Words in a piece of text: runs with a letter or digit (a figure's Markdown counts as none)."""
    if block.startswith("!["):
        return 0
    return sum(1 for w in block.split() if any(c.isalnum() for c in w))


def sections(blocks: list[str]) -> list[list[int]]:
    """A text chapter's blocks grouped into sections of about 300 words (the "pages" of a text chapter)."""
    out, current, count = [], [], 0
    for i, block in enumerate(blocks):
        current.append(i)
        count += words(block)
        if count >= SECTION_WORDS:
            out.append(current)
            current, count = [], 0
    if current:
        out.append(current)
    return out
