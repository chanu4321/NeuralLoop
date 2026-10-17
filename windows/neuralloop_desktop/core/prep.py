"""Preparing books: the just-ahead window, when to start a run on its own, "chapter ready", what a failed run
says, and how far along the pipeline is (PrepWindow.swift, AutoResume.swift, ChapterReady.swift,
RunProblemText.swift, PrepActivity.swift, NotebookLMUsage.swift)."""

import json
import math
from dataclasses import dataclass

from . import loop

MEDIA_ITEMS = {"audio", "video"}


@dataclass(frozen=True)
class Window:
    """Text items for chapters up to `text_through`, podcast and video up to `media_through`; None = all."""

    text_through: int | None
    media_through: int | None

    @property
    def chapters_spec(self) -> str:
        return _spec(self.text_through)

    @property
    def media_spec(self) -> str:
        return _spec(self.media_through)

    def includes(self, n: int, item: str) -> bool:
        if self.text_through is not None and n > self.text_through:
            return False
        return not (item in MEDIA_ITEMS and self.media_through is not None and n > self.media_through)

    def has_work(self, book: dict) -> bool:
        """An item to make (or one skipped) inside the window, or one a stopped run left being made."""
        return any(
            status == "working" or (status in ("todo", "skipped") and self.includes(c["n"], item))
            for c in book["chapters"]
            for item, status in c["status"].items()
        )


EVERYTHING = Window(None, None)


def _spec(through: int | None) -> str:
    if through is None:
        return "all"
    return "none" if through < 1 else "1" if through == 1 else f"1-{through}"


def wants_everything(setting: bool, media: str) -> bool:
    return setting or media == "all"


def window(book: dict | None, p: dict, everything: bool) -> Window:
    """F is the first open chapter not yet closed (the last when all are). Text reaches one past F, media
    up to F; once F's Read step is done both reach one further. A new book: chapter 1 whole, chapter 2's quick
    items."""
    if everything:
        return EVERYTHING
    if not book or not book["chapters"]:
        return Window(2, 1)
    chapters = book["chapters"]
    frontier = current_chapter(book, p) or chapters[-1]
    index = next((i for i, c in enumerate(chapters) if c["n"] == frontier["n"]), 0)
    read = "read" in loop.steps(p, frontier["n"])

    def through(ahead: int) -> int:
        return chapters[min(index + ahead, len(chapters) - 1)]["n"]

    return Window(through(2 if read else 1), through(1 if read else 0))


def start_again(ran_with: Window, now: Window, code: int, has_work: bool) -> bool:
    return code == 0 and has_work and ran_with != now


def is_ahead(chapter: dict) -> bool:
    return "skipped" in chapter["status"].values()


def not_yet(what: str) -> str:
    return f"{what}: Pip will prepare this when you get close."


# When the app may start a run on its own.

MINUTE_MS = 60_000.0
WAIT_AFTER_OTHER_LIMITS = 6 * 60 * MINUTE_MS


def record_after(previous: dict | None, code: int, now: float) -> dict:
    fails = 0 if code == 0 else (previous or {}).get("failuresInARow", 0) + 1
    return {"exitCode": code, "endedAt": now, "failuresInARow": fails}


def has_auto_work(book: dict, win: Window, usage: dict | None, log_modified: float, now: float) -> bool:
    if win.has_work(book):
        return True
    waiting = [
        item
        for c in book["chapters"]
        for item, s in c["status"].items()
        if s == "waiting_quota" and win.includes(c["n"], item)
    ]
    if not waiting:
        return False
    if book["engine"] != "local" and usage and usage.get("known"):
        return any(can_make(usage, item) for item in waiting)
    return now - log_modified > WAIT_AFTER_OTHER_LIMITS


def may_start(last: dict | None, settings_changed_at: float, now: float) -> bool:
    """Exit 2 and 3 wait until settings change; other failures back off 5 min, doubling, up to 6 hours."""
    if not last or last["exitCode"] == 0:
        return True
    if last["exitCode"] in (2, 3):
        return settings_changed_at > last["endedAt"]
    wait = min(5 * MINUTE_MS * 2 ** max(last["failuresInARow"] - 1, 0), WAIT_AFTER_OTHER_LIMITS)
    return now - last["endedAt"] >= wait


# "Chapter N is ready to study".


def is_complete(chapter: dict) -> bool:
    return not any(s in ("todo", "working", "waiting_quota") for s in chapter["status"].values())


def current_chapter(book: dict, p: dict) -> dict | None:
    chapters = book["chapters"]
    return next(
        (c for c in chapters if loop.is_unlocked(p, chapters, c["n"]) and not loop.is_closed(p, c["n"])), None
    )


def ready_step(book: dict, p: dict, watching: set[int], announced: set[int], quiet: bool = False):
    """(chapter to announce or None, chapters to keep watching)."""
    chapter = current_chapter(book, p)
    if chapter is None or chapter["n"] in announced:
        return None, set()
    if not is_complete(chapter):
        return None, {chapter["n"]}
    if chapter["n"] not in watching:
        return None, set()
    return (None, {chapter["n"]}) if quiet else (chapter, set())


def ready_message(chapter: dict, book_title: str) -> tuple[str, str]:
    title = f"Chapter {chapter['n']} is ready to study"
    name = f"“{chapter['title']}” in {book_title}"
    if "failed" in chapter["status"].values():
        return title, (
            f"{name} is ready to study. Pip couldn't make everything for it this time; "
            "Prepare more tries again."
        )
    status = chapter["status"]
    media = [word for item, word in (("audio", "podcast"), ("video", "video")) if status.get(item) == "done"]
    if media:
        what = f"everything is ready, {' and '.join(media)} included"
    else:
        what = "everything Pip is making for it is ready"
    return title, f"{name}: {what}. Pip saved you a spot."


def run_problem(code: int, tail: list[str] | None = None) -> str:
    tail = tail or []
    if code == 2:
        if any(t.startswith(("Invalid chapter selection", "Invalid range")) for t in tail):
            return (
                "Pip got mixed up about which chapters to prepare. Open the book and choose Prepare more to "
                "prepare them all."
            )
        return "Pip couldn't read this book. Try a different PDF or EPUB copy."
    if code == 3:
        return "Pip needs a little setup first. Open Settings to sign in to Google or choose your AI."
    return "Pip hit a snag and will try again on its own in a little while."


# NotebookLM's live usage.


def parse_usage(line: str) -> dict | None:
    if not line.startswith("NotebookLM usage: "):
        return None
    try:
        raw = json.loads(line[len("NotebookLM usage: ") :])
    except ValueError:
        return None
    if not isinstance(raw, dict):
        return None
    flags = {k: raw.get(k) is True for k in ("known", "available", "podcast", "video")}
    windows = {k: raw.get(k) if isinstance(raw.get(k), dict) else None for k in ("fiveHour", "weekly")}
    return flags | windows


def can_make(usage: dict, item: str) -> bool:
    if not (usage.get("known") and usage.get("available")):
        return False
    if item == "audio":
        return usage.get("podcast", False)
    if item == "video":
        return usage.get("video", False)
    return True


# How far along the pipeline is (activity.json).


def _num(v) -> float | None:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def read_activity(data: bytes) -> dict | None:
    """Lenient: a bad entry is skipped; a file that isn't a JSON object reads as None."""
    try:
        root = json.loads(data)
    except ValueError:
        return None
    if not isinstance(root, dict):
        return None
    items = []
    for e in root.get("items") if isinstance(root.get("items"), list) else []:
        if isinstance(e, dict) and _num(e.get("n")) is not None and isinstance(e.get("item"), str):
            done, total = _num(e.get("done")), _num(e.get("total"))
            items.append(
                {
                    "n": int(_num(e["n"])),
                    "item": e["item"],
                    "by": e.get("by") if isinstance(e.get("by"), str) else "",
                    "step": e.get("step") if isinstance(e.get("step"), str) else "",
                    "started": _num(e.get("started")) or 0.0,
                    "done": int(done) if done is not None else None,
                    "total": int(total) if total is not None else None,
                    "fraction": _num(e.get("fraction")),
                    "expected": _num(e.get("expected")),
                }
            )
    queue = [
        {"n": int(_num(e["n"])), "item": e["item"]}
        for e in (root.get("queue") if isinstance(root.get("queue"), list) else [])
        if isinstance(e, dict) and _num(e.get("n")) is not None and isinstance(e.get("item"), str)
    ]
    updated = _num(root.get("updated")) or 0.0
    return {"updated": updated, "ended": root.get("ended") is True, "items": items, "queue": queue}


SLOW_AFTER = 45.0


def _minutes(seconds: float) -> str:
    m = math.floor(seconds / 60 + 0.5)
    return "1 min" if m <= 1 else f"{m} min"


def _so_far(seconds: float) -> str:
    return "Just started" if seconds < SLOW_AFTER else f"{_minutes(seconds)} so far"


def _left(seconds: float) -> str:
    return "Almost there" if seconds < 45 else f"About {_minutes(seconds)} left"


def item_progress(item: dict, now: float) -> dict:
    """A bar value (0 to 1, or None) and plain words for one item being made."""
    elapsed = max(0.0, (now - item["started"]) / 1000)
    base = {"step": item["step"], "by": item["by"], "slow": False, "estimated": False}
    overall = item.get("fraction")
    if overall is not None and overall > 0:
        parts = []
        if item.get("total"):
            parts.append(f"{min(item.get('done') or 0, item['total'])} of {item['total']}")
        parts.append(_so_far(elapsed))
        if overall < 1 and elapsed > 0:
            parts.append(_left(elapsed / overall * (1 - overall)))
        detail = " · ".join(parts).lower()
        return {**base, "fraction": min(0.99, max(0.02, overall)), "detail": detail[:1].upper() + detail[1:]}
    if item.get("total"):
        total = item["total"]
        done = min(item.get("done") or 0, total)
        detail = f"{done} of {total} · " + _so_far(elapsed).lower()
        if 0 < done < total:
            detail += " · " + _left(elapsed / done * (total - done)).lower()
        return {**base, "fraction": min(0.99, max(0.02, done / total)), "detail": detail}
    expected = item.get("expected")
    if expected and expected > 0:
        ratio = elapsed / expected
        fraction = 0.9 * ratio if ratio < 1 else 0.9 + 0.09 * (1 - math.exp(-(ratio - 1)))
        slow = ratio > 1.3 and elapsed >= SLOW_AFTER
        why = ": NotebookLM can be slow when it's busy." if item["by"] == "NotebookLM" else "."
        if slow:
            detail = _so_far(elapsed) + ", longer than usual. It's still going" + why
        else:
            detail = _so_far(elapsed) + " · " + _left(expected - elapsed).lower()
        return {**base, "fraction": max(0.02, fraction), "detail": detail, "slow": slow, "estimated": True}
    return {**base, "fraction": None, "detail": _so_far(elapsed)}


def percent_text(progress: dict) -> str | None:
    """ "69%", or "About 34%" when it's an estimate; None when there's nothing to measure."""
    if progress.get("fraction") is None:
        return None
    pct = math.floor(progress["fraction"] * 100 + 0.5)
    return f"About {pct}%" if progress.get("estimated") else f"{pct}%"


def place_text(place: int) -> str:
    if place == 0:
        return "Next up"
    n = place + 1
    suffix = "th" if 11 <= n % 100 <= 13 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix} in line"
