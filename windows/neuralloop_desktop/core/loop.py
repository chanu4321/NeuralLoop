"""The five-step loop per chapter, unlocking, spaced repetition, cards, and steps that complete themselves
(Loop.swift, FSRS.swift, Cards.swift, AutoSteps.swift)."""

import math

from . import coverage
from .jsonish import rounded

STAGES = ("prime", "read", "recall", "map", "space")
LABELS = {"prime": "Listen & watch", "read": "Read", "recall": "Recall", "map": "Map", "space": "Remember"}


def steps(p: dict, n: int) -> dict:
    return p["loop"].get(str(n), {})


def is_closed(p: dict, n: int) -> bool:
    done = steps(p, n)
    return all(s in done for s in STAGES)


def next_stage(p: dict, n: int) -> str | None:
    done = steps(p, n)
    return next((s for s in STAGES if s not in done), None)


def is_unlocked(p: dict, chapters: list[dict], n: int) -> bool:
    """Chapter 1 is always open; every other chapter opens when the one before it is closed."""
    index = next((i for i, c in enumerate(chapters) if c["n"] == n), None)
    if index is None or index == 0:
        return True
    return is_closed(p, chapters[index - 1]["n"])


def complete(p: dict, n: int, stage: str, now: float) -> bool:
    """Record a finished step. True when this closed the loop for the first time."""
    mine = p["loop"].setdefault(str(n), {})
    mine.setdefault(stage, now)
    p["updatedAt"] = max(p["updatedAt"], now)
    if is_closed(p, n) and "closedShown" not in mine:
        mine["closedShown"] = 1
        return True
    return False


def complete_if_open(p: dict, chapters: list[dict], n: int, stage: str, now: float) -> bool | None:
    """A step the person earned: only in an open chapter, only if not done yet. None when nothing changed."""
    if not any(c["n"] == n for c in chapters) or not is_unlocked(p, chapters, n) or stage in steps(p, n):
        return None
    return complete(p, n, stage, now)


def is_mapped(p: dict, n: int) -> bool:
    return "map" in steps(p, n)


# FSRS-4.5, exactly as the study site and the Swift app schedule cards.

W = [
    0.4872,
    1.4003,
    3.7145,
    13.8206,
    5.1618,
    1.2298,
    0.8975,
    0.031,
    1.6474,
    0.1367,
    1.0461,
    2.1072,
    0.0793,
    0.3246,
    1.587,
    0.2272,
    2.8755,
]
DECAY = -0.5
FACTOR = 19.0 / 81.0
DAY_MS = 86_400_000.0
RELEARN_MS = 10.0 * 60_000
MAX_INTERVAL_DAYS = 365.0
RATINGS = {"again": 1, "hard": 2, "good": 3, "easy": 4}


def retrievability(elapsed_days: float, stability: float) -> float:
    return (1 + FACTOR * elapsed_days / stability) ** DECAY


def _clamp(d: float) -> float:
    return min(10.0, max(1.0, d))


def grade(card: dict | None, rating: int, now: float) -> dict:
    card = card or {"s": 0.0, "d": 0.0, "reps": 0, "last": 0.0, "due": 0.0}
    r = float(rating)
    nxt = dict(card)
    if card["reps"] == 0:
        nxt["s"] = W[rating - 1]
        nxt["d"] = _clamp(W[4] - (r - 3) * W[5])
    else:
        recall = retrievability(max(0.0, now - card["last"]) / DAY_MS, card["s"])
        d = card["d"]
        nxt["d"] = _clamp(W[7] * (W[4] - W[5]) + (1 - W[7]) * (d - W[6] * (r - 3)))
        if rating == 1:
            nxt["s"] = W[11] * d ** -W[12] * ((card["s"] + 1) ** W[13] - 1) * math.exp(W[14] * (1 - recall))
        else:
            hard = W[15] if rating == 2 else 1
            easy = W[16] if rating == 4 else 1
            nxt["s"] = card["s"] * (
                1
                + math.exp(W[8])
                * (11 - d)
                * card["s"] ** -W[9]
                * (math.exp(W[10] * (1 - recall)) - 1)
                * hard
                * easy
            )
    nxt["s"] = max(0.1, nxt["s"])
    nxt["reps"] = card["reps"] + 1
    nxt["last"] = now
    nxt["due"] = (
        now + RELEARN_MS
        if rating == 1
        else now + min(MAX_INTERVAL_DAYS, max(1.0, rounded(nxt["s"]))) * DAY_MS
    )
    return nxt


def unlocked_cards(chapters: list[dict], p: dict) -> list[dict]:
    return [
        {"id": f"{c['n']}:{i}", "chapter": c["n"], "card": card}
        for c in chapters
        if is_unlocked(p, chapters, c["n"])
        for i, card in enumerate(c["cards"])
    ]


def due_cards(chapters: list[dict], p: dict, now: float) -> list[dict]:
    """Cards never reviewed, or whose review is due."""
    return [
        c
        for c in unlocked_cards(chapters, p)
        if c["id"] not in p["cards"] or p["cards"][c["id"]]["due"] <= now
    ]


# Steps that complete themselves (spec 09).


def quiz_state(value) -> dict:
    """progress.quiz["n"] as {i, results} (lenient)."""
    out = {"i": 0, "results": []}
    if isinstance(value, dict):
        if isinstance(value.get("i"), (int, float)) and not isinstance(value.get("i"), bool):
            out["i"] = max(0, int(value["i"]))
        if isinstance(value.get("results"), list):
            out["results"] = [r is True for r in value["results"]]
    return out


def quiz_is_great(state: dict, total: int) -> bool:
    """80% or better is worth confetti."""
    return total > 0 and sum(state["results"]) >= math.ceil(total * 0.8)


def quiz_finished(p: dict, chapter: dict) -> bool:
    return bool(chapter["quiz"]) and quiz_state(p["quiz"].get(str(chapter["n"])))["i"] >= len(chapter["quiz"])


def is_real_answer(answer: str) -> bool:
    """A real try: at least five words, not the same one over and over."""
    words = [w for w in "".join(c if c.isalnum() else " " for c in answer.lower()).split() if w]
    return len(words) >= 5 and len(set(words)) >= 3


def cards_seen(p: dict, chapter: dict) -> int:
    seen = 0
    for i in range(len(chapter["cards"])):
        card = p["cards"].get(f"{chapter['n']}:{i}")
        if card and (card["reps"] >= 1 or card["last"] > 0):
            seen += 1
    return seen


def cards_all_seen(p: dict, chapter: dict) -> bool:
    return bool(chapter["cards"]) and cards_seen(p, chapter) == len(chapter["cards"])


def record_play(p: dict, n: int, kind: str, start: float, end: float, rate: float, wall: float) -> bool:
    """A stretch of the chapter's podcast or video played; leaves updatedAt alone like study time."""
    w = p["watch"].get(str(n)) or {"audio": [], "video": []}
    w[kind], counted = coverage.add(w[kind], start, end, rate, wall)
    if counted:
        p["watch"][str(n)] = w
    return counted


def credit_reading(
    p: dict, n: int, visible: list[int], seconds: float, page_count: int, earning: bool
) -> bool:
    record = p["reading"].get(str(n)) or {"pages": {}, "count": 0, "last": None}
    if not coverage.credit(record, visible, seconds, page_count, earning):
        return False
    p["reading"][str(n)] = record
    return True
