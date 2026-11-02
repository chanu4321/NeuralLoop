"""Recall, remaking the mind map from memory, plain math, the study log and year grid, and the shelf
(Remake.swift, RecallCheck.swift, Activity.swift, Shelf.swift)."""

import datetime as dt
import math
import re

from . import loop

# Remaking the mind map from memory.

STOP_WORDS = {"with", "that", "this", "from", "into", "your", "about", "when", "what", "they", "their"}
MINIMUM_SUBSTRING = 4


def _significant(text: str) -> list[str]:
    cleaned = "".join(c if c.isalnum() else " " for c in text.lower())
    return [w for w in cleaned.split() if len(w) > 3 and w not in STOP_WORDS]


def names_match(guess: str, truth: str) -> bool:
    """Does a remembered branch name match the real one? Tolerates word forms and extra words."""
    g, t = guess.lower().strip(), truth.lower().strip()
    if not g or not t:
        return False
    if g == t:
        return True
    if min(len(g), len(t)) >= MINIMUM_SUBSTRING and (t in g or g in t):
        return True
    gw, tw = _significant(guess), _significant(truth)
    if not gw or not tw:
        return False

    def same_stem(a: str, b: str) -> bool:
        return a == b or (len(a) > 4 and len(b) > 4 and a[:5] == b[:5])

    hits = sum(1 for w in tw if any(same_stem(x, w) for x in gw))
    return hits / len(tw) >= 0.5


def compare(typed: str, mind: dict) -> dict:
    """What someone typed ("Branch" lines, "- sub-idea" lines) against the real mind map."""
    lines = [line.strip() for line in typed.split("\n") if line.strip()]
    everything = [line.lstrip("-").strip() if line.startswith("-") else line for line in lines]
    found = total = 0
    rows = []
    for branch in mind.get("children", []):
        children = []
        for child in branch.get("children", []):
            hit = any(names_match(x, child["name"]) for x in everything)
            found += hit
            total += 1
            children.append({"name": child["name"], "remembered": hit, "children": []})
        remembered = any(names_match(x, branch["name"]) for x in everything)
        found += remembered
        total += 1
        rows.append({"name": branch["name"], "remembered": remembered, "children": children})
    percent = math.floor(100 * found / total + 0.5) if total else 0
    return {"rows": rows, "lines": lines, "percent": percent}


# Plain math: models sometimes write LaTeX ("$M \times N$"); show it as plain text.

SYMBOLS = [
    ("\\times", "×"),
    ("\\cdot", "·"),
    ("\\rightarrow", "→"),
    ("\\to", "→"),
    ("\\leftarrow", "←"),
    ("\\leq", "≤"),
    ("\\le", "≤"),
    ("\\geq", "≥"),
    ("\\ge", "≥"),
    ("\\neq", "≠"),
    ("\\approx", "≈"),
    ("\\infty", "∞"),
    ("\\pm", "±"),
    ("\\{", "{"),
    ("\\}", "}"),
    ("\\%", "%"),
    ("\\,", " "),
]
_MATH = re.compile(r"\$\$?([^\s$](?:[^$]*[^\s$])?)\$\$?")
_TEXT = re.compile(r"\\(?:text|mathrm|mathbf)\{([^}]*)\}")


def plain_math(text: str) -> str:
    if "$" not in text and "\\" not in text:
        return text
    for latex, symbol in SYMBOLS:
        text = text.replace(latex, symbol)
    text = _MATH.sub(lambda m: m.group(1), text)
    return _TEXT.sub(lambda m: m.group(1), text)


# A recall answer graded by word matching when no model can (same rule as the pipeline's `word_match`).

RECALL_STOP = {
    "that",
    "this",
    "with",
    "from",
    "have",
    "they",
    "their",
    "what",
    "when",
    "your",
    "into",
    "than",
    "then",
}


def _stems(text: str) -> set[str]:
    words = "".join(c if (c.isalnum() or c == "'") else " " for c in text.lower()).split()
    return {w[:5] for w in words if len(w) > 3 and w not in RECALL_STOP}


def word_match(key_points: list[str], answer: str) -> list[bool]:
    said = _stems(answer)
    out = []
    for point in key_points:
        words = _stems(point)
        out.append(bool(words) and len(words & said) / len(words) >= 0.6)
    return out


def recall_feedback(key_points: list[str], covered: list[bool]) -> str:
    missing = [k for k, c in zip(key_points, covered, strict=False) if not c]
    remembered = [k for k, c in zip(key_points, covered, strict=False) if c]
    if not missing:
        return "You covered every key point. Lovely recall!"
    if remembered:
        return f"Nice: you remembered that {remembered[0]}. Next time, also add that {missing[0]}."
    return f"Good start. Next time, try to include that {missing[0]}."


# The study log.

LEVEL_STARTS = [0, 10 * 60, 20 * 60, 45 * 60]
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def day_key(ms: float) -> str:
    return dt.datetime.fromtimestamp(ms / 1000).strftime("%Y-%m-%d")


def log_study(p: dict, now: float, seconds: float) -> None:
    """Study time isn't a change to merge by: it leaves updatedAt alone."""
    if seconds <= 0:
        return
    key = day_key(now)
    p["log"][key] = p["log"].get(key, 0.0) + seconds


def partial_tick(last_tick: float, active_since: float | None, until: float, every: float = 15) -> float:
    if active_since is None:
        return 0.0
    return min(every, max(0.0, until - max(last_tick, active_since)))


def level(seconds: float) -> int:
    return 0 if seconds <= 0 else sum(1 for s in LEVEL_STARTS if seconds >= s)


def year_grid(log: dict, today_ms: float) -> dict:
    """53 weeks of 7 days (Sunday first) ending with this week, and month labels by week index."""
    end = dt.datetime.fromtimestamp(today_ms / 1000).date()
    weekday = (end.weekday() + 1) % 7  # Sunday = 0
    start = end - dt.timedelta(days=52 * 7 + weekday)
    weeks, labels = [], []
    for w in range(53):
        week = []
        for d in range(7):
            date = start + dt.timedelta(days=w * 7 + d)
            key = date.strftime("%Y-%m-%d")
            seconds = log.get(key, 0.0)
            week.append({"date": key, "seconds": seconds, "level": level(seconds), "future": date > end})
        first = start + dt.timedelta(days=w * 7)
        if w == 0 or (first - dt.timedelta(days=7)).month != first.month:
            labels.append({"week": w, "label": MONTHS[first.month - 1]})
        weeks.append(week)
    return {"weeks": weeks, "months": labels}


def year_stats(log: dict, today_ms: float) -> dict:
    """Totals for the last 365 days. Only positive framing: no "streak lost"."""
    end = dt.datetime.fromtimestamp(today_ms / 1000).date()
    total, days, run, longest, best = 0.0, 0, 0, 0, None
    for back in range(364, -1, -1):
        key = (end - dt.timedelta(days=back)).strftime("%Y-%m-%d")
        seconds = log.get(key, 0.0)
        total += seconds
        if seconds > 0:
            days += 1
            run += 1
            longest = max(longest, run)
            if seconds > (best["seconds"] if best else 0):
                best = {"date": key, "seconds": seconds}
        else:
            run = 0
    return {"total": total, "days": days, "longestRun": longest, "best": best}


def format_duration(seconds: float) -> str:
    minutes = max(1, math.floor(seconds / 60 + 0.5)) if seconds > 0 else 0
    if minutes < 60:
        return f"{minutes} min"
    return f"{minutes // 60} h" if minutes % 60 == 0 else f"{minutes // 60} h {minutes % 60} min"


# The shelf.


def dots(chapters: list[dict], p: dict) -> list[str]:
    """One per chapter: closed, open (the one to study), ready (opens later), preparing."""
    out = []
    for c in chapters:
        if loop.is_closed(p, c["n"]):
            out.append("closed")
        elif c["status"].get("study") != "done":
            out.append("preparing")
        else:
            out.append("open" if loop.is_unlocked(p, chapters, c["n"]) else "ready")
    return out


def combined_log(logs: list[dict]) -> dict:
    total: dict[str, float] = {}
    for log in logs:
        for day, seconds in log.items():
            total[day] = total.get(day, 0.0) + seconds
    return total


def cover_index(title: str, count: int) -> int:
    """Stable across launches (and the same as the Mac's), so a book keeps its colour."""
    if count <= 0:
        return 0
    total = 0
    for offset, ch in enumerate(title):
        total = (total + ord(ch) * (offset + 1)) & 0xFFFFFFFFFFFFFFFF
    if total >= 1 << 63:  # Swift's Int wraps around; abs of the signed value
        total -= 1 << 64
    return abs(total) % count


def shelf_summary(entries: list[dict], now_ms: float) -> dict:
    """What the shelf's greeting and the tray panel show (ShelfSummary): where you left off, cards ready, this
    week's study time and closed loops, and the books being prepared. `entries`: {id, book, progress,
    preparing}."""
    week_ago = now_ms - 7 * loop.DAY_MS
    summary = {"resume": None, "dueCards": 0, "weekSeconds": 0.0, "loopsClosedThisWeek": 0, "preparing": []}
    latest = 0.0
    for entry in entries:
        if entry.get("preparing"):
            summary["preparing"].append(entry["id"])
        b, p = entry.get("book"), entry["progress"]
        if not b:
            continue
        due = loop.due_cards(b["chapters"], p, now_ms)
        summary["dueCards"] += sum(1 for c in due if c["id"] in p["cards"])
        for back in range(7):
            summary["weekSeconds"] += p["log"].get(day_key(now_ms - back * loop.DAY_MS), 0.0)
        summary["loopsClosedThisWeek"] += sum(
            1 for steps in p["loop"].values() if steps.get("space", 0) > week_ago and "closedShown" in steps
        )
        last = p.get("last")
        if last and p["updatedAt"] > latest:
            chapter = next((c for c in b["chapters"] if c["n"] == last["n"]), None)
            stage = loop.next_stage(p, last["n"]) or (last["stage"] if last["stage"] in loop.STAGES else None)
            if chapter and stage:
                latest = p["updatedAt"]
                summary["resume"] = {
                    "id": entry["id"],
                    "n": chapter["n"],
                    "title": chapter["title"],
                    "stage": stage,
                }
    return summary
