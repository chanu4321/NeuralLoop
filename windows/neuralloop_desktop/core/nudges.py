"""Pip's nudges (Nudges.swift): at most one a day, only when something small is worth doing, never in quiet
hours, backing off when ignored. Away a while, Silly mode turns them dramatic on purpose, step by step (a tiny
sad violin at 8 h, a sad meow song at 12 h, a shocked "fahhh" at 24 h by default), each once per absence and
only with real news; with nothing to do, one "Pip's ready when you are" a week at most. `decide` is pure; the
app gathers the inputs.

Settings and history are dicts in the same JSON shapes the Mac app saves."""

import datetime as dt
import uuid

from . import loop, prep
from .jsonish import rounded

DAY_MS = 86_400_000.0
HOUR_MS = 3_600_000.0
MINIMUM_DUE_CARDS = 3
SECONDS_PER_CARD = 15
MOODS = ("gentle", "sadViolin", "sadMeow", "shocked")
SILLY_SOUNDS = ("sadViolin", "sadMeow", "shocked")
MOOD_NAMES = {
    "gentle": "The usual chime",
    "sadViolin": "🎻 Sad violin",
    "sadMeow": "😿 Sad meow song",
    "shocked": "😱 Fahhh",
}
HOUR_RANGE = (1.0, 168.0)
REPEAT_RANGE = (1.0, 48.0)
MOST_STEPS = 8
NEXT_STEP = {
    "prime": "watch or listen",
    "read": "read with your guide",
    "recall": "recall it in your own words",
    "map": "remake the map from memory",
    "space": "review your flashcards",
}


def _clamp_hours(hours: float) -> float:
    return min(max(rounded(hours), HOUR_RANGE[0]), HOUR_RANGE[1])


def step(sound: str, hours: float, step_id: str | None = None) -> dict:
    return {"id": step_id or str(uuid.uuid4()).upper(), "sound": sound, "hours": _clamp_hours(hours)}


def default_steps() -> list[dict]:
    return [step("sadViolin", 8), step("sadMeow", 12), step("shocked", 24)]


def default_settings() -> dict:
    return {
        "enabled": True,
        "chapterReady": True,
        "nudges": True,
        "quietStart": 22,
        "quietEnd": 8,
        "pausedUntil": 0.0,
        "sillySounds": True,
        "steps": default_steps(),
        "repeatHours": 0.0,
        "bigPip": True,
        "volume": 0.8,
    }


def _nearest_free(hours: float, taken: set[float]) -> float:
    h = hours
    while h <= HOUR_RANGE[1]:
        if h not in taken:
            return h
        h += 1
    h = hours
    while h >= HOUR_RANGE[0]:
        if h not in taken:
            return h
        h -= 1
    return hours


def separated(steps: list[dict]) -> list[dict]:
    """Saved steps sharing an hour move to the nearest free one (later first), keeping their order."""
    taken: set[float] = set()
    out = []
    for s in steps:
        hours = _nearest_free(s["hours"], taken)
        taken.add(hours)
        out.append({**s, "hours": hours})
    return out


def free_hours(steps: list[dict]) -> float:
    """Hours for a new step: four after the last one, or the nearest free hour."""
    taken = {s["hours"] for s in steps}
    return _nearest_free(_clamp_hours(max((s["hours"] for s in steps), default=4) + 4), taken)


def repeat_choice(hours: float) -> float:
    return 0.0 if hours <= 0 else min(max(rounded(hours), REPEAT_RANGE[0]), REPEAT_RANGE[1])


def parse_settings(raw) -> dict:
    """Settings saved by earlier versions keep what they had; anything new starts at its default."""
    d = default_settings()
    if not isinstance(raw, dict):
        return d
    for key in ("enabled", "chapterReady", "nudges", "sillySounds", "bigPip"):
        if isinstance(raw.get(key), bool):
            d[key] = raw[key]
    for key in ("quietStart", "quietEnd"):
        if isinstance(raw.get(key), int) and not isinstance(raw.get(key), bool):
            d[key] = raw[key] % 24
    if isinstance(raw.get("pausedUntil"), (int, float)) and not isinstance(raw.get("pausedUntil"), bool):
        d["pausedUntil"] = float(raw["pausedUntil"])
    if isinstance(raw.get("steps"), list):
        kept = []
        for s in raw["steps"]:
            if isinstance(s, dict) and s.get("sound") in SILLY_SOUNDS:
                hours = s.get("hours") if isinstance(s.get("hours"), (int, float)) else 0
                kept.append(step(s["sound"], hours, s.get("id") if isinstance(s.get("id"), str) else None))
        d["steps"] = separated(kept[:MOST_STEPS])
    elif raw.get("fahhh") is False:
        d["steps"] = [s for s in d["steps"] if s["sound"] != "shocked"]
    if isinstance(raw.get("repeatHours"), (int, float)):
        d["repeatHours"] = repeat_choice(float(raw["repeatHours"]))
    if isinstance(raw.get("volume"), (int, float)) and not isinstance(raw.get("volume"), bool):
        d["volume"] = min(max(float(raw["volume"]), 0.0), 1.0)
    return d


def default_history() -> dict:
    return {
        "lastSent": 0.0,
        "lastSentDay": "",
        "ignoredInARow": 0,
        "lastEngaged": 0.0,
        "lastMood": None,
        "lastSillySent": 0.0,
        "lastStepId": None,
        "lastMissedYou": 0.0,
    }


def parse_history(raw) -> dict:
    h = default_history()
    if not isinstance(raw, dict):
        return h
    for key in ("lastSent", "lastEngaged", "lastSillySent", "lastMissedYou"):
        if isinstance(raw.get(key), (int, float)) and not isinstance(raw.get(key), bool):
            h[key] = float(raw[key])
    if isinstance(raw.get("lastSentDay"), str):
        h["lastSentDay"] = raw["lastSentDay"]
    if isinstance(raw.get("ignoredInARow"), int) and not isinstance(raw.get("ignoredInARow"), bool):
        h["ignoredInARow"] = raw["ignoredInARow"]
    if raw.get("lastMood") in MOODS:
        h["lastMood"] = raw["lastMood"]
    if isinstance(raw.get("lastStepId"), str):
        h["lastStepId"] = raw["lastStepId"]
    return h


def ladder(settings: dict) -> list[dict]:
    """The steps in the order they come (same hours: in the order saved)."""
    return [s for _, s in sorted(enumerate(settings["steps"]), key=lambda e: (e[1]["hours"], e[0]))]


def in_quiet_hours(hour: int, start: int, end: int) -> bool:
    if start == end:
        return False
    return (hour >= start or hour < end) if start > end else (start <= hour < end)


def is_quiet(settings: dict, now: float, hour: int) -> bool:
    return now < settings["pausedUntil"] or in_quiet_hours(hour, settings["quietStart"], settings["quietEnd"])


def allows(settings: dict, kind: str) -> bool:
    if not settings["enabled"]:
        return False
    return {
        "chapterReady": settings["chapterReady"],
        "nudges": settings["nudges"],
        "silly": settings["sillySounds"],
    }[kind]


def sent(history: dict, nudge: dict, now: float, day: str) -> None:
    """Record a nudge going out. A usual one sent after your last visit is ignored; silly ones never count."""
    mood = nudge["mood"]
    history["lastMood"] = mood
    if mood == "gentle":
        ignored = history["lastSent"] > 0 and history["lastEngaged"] < history["lastSent"]
        history["ignoredInARow"] = history["ignoredInARow"] + 1 if ignored else 0
        history["lastSent"], history["lastSentDay"] = now, day
    else:
        history["lastSillySent"] = now
        if nudge.get("step"):
            history["lastStepId"] = nudge["step"]["id"]
        if nudge.get("missesYou"):
            history["lastMissedYou"] = now


def engaged(history: dict, now: float) -> None:
    history["lastEngaged"], history["ignoredInARow"] = now, 0


def _sent_place(history: dict, steps: list[dict]) -> int | None:
    if history["lastSillySent"] <= history["lastEngaged"]:
        return None
    if history["lastStepId"]:
        for i, s in enumerate(steps):
            if s["id"] == history["lastStepId"]:
                return i
    hours_then = (history["lastSillySent"] - history["lastEngaged"]) / HOUR_MS
    places = [i for i, s in enumerate(steps) if s["hours"] <= hours_then]
    return places[-1] if places else None


def silly_step(settings: dict, history: dict, now: float) -> int | None:
    if not settings["sillySounds"] or history["lastEngaged"] <= 0 or now < history["lastEngaged"]:
        return None
    steps = ladder(settings)
    hours_away = (now - history["lastEngaged"]) / HOUR_MS
    due_places = [i for i, s in enumerate(steps) if s["hours"] <= hours_away]
    if not due_places:
        return None
    due = due_places[-1]
    due_group = next(i for i, s in enumerate(steps) if s["hours"] == steps[due]["hours"])
    sent_place = _sent_place(history, steps)
    if sent_place is None:
        return due_group
    nxt = max(sent_place + 1, due_group)
    if nxt <= due:
        return nxt
    repeats = settings["repeatHours"] > 0 and sent_place == len(steps) - 1 and due == sent_place
    return due if repeats and now - history["lastSillySent"] >= settings["repeatHours"] * HOUR_MS else None


def nudge(
    title: str,
    body: str,
    mood: str = "gentle",
    step_: dict | None = None,
    misses_you: bool = False,
    headline: str | None = None,
) -> dict:
    return {
        "title": title,
        "body": body,
        "mood": mood,
        "step": step_,
        "missesYou": misses_you,
        "headline": title if headline is None else headline,
    }


def _how_long(hours: float) -> str:
    if hours < 24:
        h = max(int(hours), 1)
        return f"{h} hour{'' if int(hours) == 1 else 's'}"
    days = int(hours / 24)
    return "A whole day" if days == 1 else f"{days} days"


def told(
    news: dict, mood: str, hours_away: float, step_: dict | None = None, misses_you: bool = False
) -> dict:
    """The same news, told the silly way."""
    if mood == "gentle":
        return news
    title = {
        "sadViolin": "🎻 Pip is playing a tiny sad violin",
        "sadMeow": "😿 Pip wrote you a sad little song",
        "shocked": f"😱 FAHHH! {_how_long(hours_away)}?!",
    }[mood]
    body = news["body"] if not news["headline"] else f"{news['headline']}. {news['body']}"
    return nudge(title, body, mood, step_, misses_you)


def sample(mood: str) -> dict:
    test = nudge("🐾 Hi from Pip", "This is how a nudge looks and sounds.", headline="Hi from Pip")
    return told(test, mood, 24)


def reviewed_cards_due(p: dict, now: float) -> int:
    return sum(1 for c in p["cards"].values() if c["reps"] > 0 and c["due"] <= now)


def _due_cards_nudge(books: list[tuple[dict, dict]], now: float) -> dict | None:
    due = sum(reviewed_cards_due(p, now) for _, p in books)
    if due < MINIMUM_DUE_CARDS:
        return None
    minutes = (due * SECONDS_PER_CARD + 59) // 60
    return nudge(
        f"🐾 {due} cards are ready",
        f"About {minutes} min with Pip, then you're done for today.",
        headline=f"{due} cards are ready",
    )


def _half_done_nudge(books: list[tuple[dict, dict]], now: float) -> dict | None:
    best = None
    for book, p in books:
        for chapter, steps in p["loop"].items():
            done = [steps[s] for s in loop.STAGES if s in steps]
            if not done or len(done) == len(loop.STAGES):
                continue
            touched = max(done)
            if now - touched < DAY_MS / 2 or touched <= (best[0] if best else -1):
                continue
            nxt = next((NEXT_STEP[s] for s in loop.STAGES if s not in steps), "keep going")
            match = next((c for c in book["chapters"] if str(c["n"]) == chapter), None)
            if match is not None and not prep.is_complete(match):
                continue
            best = (touched, match["title"] if match else "your chapter", nxt)
    if not best:
        return None
    return nudge(
        f"🧶 Loose yarn in “{best[1]}”",
        f"Next: {best[2]}. Pip saved your spot.",
        headline=f"Loose yarn in “{best[1]}”",
    )


def decide(
    books: list[tuple[dict, dict]],
    settings: dict,
    history: dict,
    now: float,
    hour: int,
    today: str,
    app_active: bool = False,
) -> dict | None:
    """Should Pip nudge now, and with what? `books` pairs each book with this device's progress."""
    if not settings["enabled"] or is_quiet(settings, now, hour):
        return None
    news = _due_cards_nudge(books, now) or _half_done_nudge(books, now)
    if not app_active and books:
        place = silly_step(settings, history, now)
        if place is not None:
            chosen = ladder(settings)[place]
            hours_away = (now - history["lastEngaged"]) / HOUR_MS
            if news:
                return told(news, chosen["sound"], hours_away, chosen)
            if now - history["lastMissedYou"] >= 7 * DAY_MS:
                hi = nudge("🐾", "Pip's ready when you are. Even five minutes counts.", headline="")
                return told(hi, chosen["sound"], hours_away, chosen, misses_you=True)
    if not allows(settings, "nudges"):
        return None
    if history["lastSentDay"] == today:
        return None
    if history["ignoredInARow"] >= 2 and now - history["lastSent"] < 2 * DAY_MS:
        return None
    away_a_week = history["lastEngaged"] > 0 and now - history["lastEngaged"] > 7 * DAY_MS
    if away_a_week and now - history["lastSent"] < 7 * DAY_MS:
        return None
    return news


def pause_until_tomorrow(now: dt.datetime, quiet_end: int) -> float:
    """The next end of quiet hours after `now` (pressed after midnight, that's this morning)."""
    hour = min(max(quiet_end, 0), 23)
    this_morning = now.replace(hour=hour, minute=0, second=0, microsecond=0)
    if this_morning > now:
        return this_morning.timestamp() * 1000
    return (this_morning + dt.timedelta(days=1)).timestamp() * 1000


def emoji(n: dict) -> str:
    """The title's leading emoji (shown big on screen), or ""."""
    first = n["title"][:1]
    return first if first and ord(first) >= 0x2300 and not first.isalnum() else ""


def words(n: dict) -> str:
    e = emoji(n)
    return n["title"][len(e) :].strip() if e else n["title"]


# How a silly nudge arrives (NudgeDelivery.swift): the big on-screen Pip with its own sound only when nothing
# else is going on (screen locked, something full screen, or the microphone in use keep it a notification).


def shows_big_pip(mood: str, settings: dict, moment: dict) -> bool:
    return (
        mood != "gentle"
        and settings["bigPip"]
        and not moment.get("screenLocked")
        and not moment.get("fullScreenInFront")
        and not moment.get("microphoneInUse")
    )


def player(mood: str, settings: dict, moment: dict, test: bool) -> str:
    """ "bigPip", "app" (a test from Settings is always heard), or "notification"."""
    if shows_big_pip(mood, settings, moment):
        return "bigPip"
    return "app" if test and mood != "gentle" else "notification"


def needs_moment(mood: str, settings: dict) -> bool:
    return mood != "gentle" and settings["bigPip"]
