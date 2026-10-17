"""Nudges.swift and NudgeDelivery.swift: the same cases as NudgeTests."""

import datetime as dt

from neuralloop_desktop.core import nudges, progress

from .conftest import make_book

DAY = 86_400_000.0
HOUR = 3_600_000.0
NOW = 10 * DAY
DEFAULTS = nudges.default_steps()


def titled(titles: dict[int, str] | None = None, status: dict | None = None) -> dict:
    from neuralloop_desktop.core import book

    return make_book(
        [book.chapter({"n": n, "title": t, "status": status or {}}) for n, t in (titles or {}).items()]
    )


def due_cards(reps: int, count: int):
    p = progress.empty()
    for i in range(count):
        p["cards"][f"1:{i}"] = {"s": 1, "d": 5, "reps": reps, "last": 0, "due": NOW - 1}
    return titled(), p


def settings(steps=None, repeat=0.0, **changes) -> dict:
    s = nudges.default_settings()
    s["steps"] = DEFAULTS if steps is None else steps
    s["repeatHours"] = repeat
    s.update(changes)
    return s


def decide(books, history=None, hour=18, s=None, app_active=False):
    return nudges.decide(
        books, s or settings(), history or nudges.default_history(), NOW, hour, "today", app_active
    )


def away(hours: float, sent_step: dict | None = None) -> dict:
    h = nudges.default_history()
    h["lastEngaged"] = NOW - hours * HOUR
    if sent_step:
        nudges.sent(h, {"mood": sent_step["sound"], "step": sent_step}, NOW - 1, "earlier")
    return h


def gentle_sent(h: dict, at: float, day: str) -> None:
    nudges.sent(h, {"mood": "gentle"}, at, day)


def test_pause_until_tomorrow_resumes_at_the_next_end_of_quiet_hours():
    morning = dt.datetime(2026, 3, 11, 8)
    assert nudges.pause_until_tomorrow(dt.datetime(2026, 3, 10, 20, 30), 8) == morning.timestamp() * 1000
    assert nudges.pause_until_tomorrow(dt.datetime(2026, 3, 11, 1, 30), 8) == morning.timestamp() * 1000
    assert (
        nudges.pause_until_tomorrow(dt.datetime(2026, 3, 11, 9, 30), 8)
        == (morning + dt.timedelta(days=1)).timestamp() * 1000
    )


def test_quiet_hours_wrap_past_midnight():
    assert nudges.in_quiet_hours(23, 22, 8) and nudges.in_quiet_hours(3, 22, 8)
    assert not nudges.in_quiet_hours(12, 22, 8) and not nudges.in_quiet_hours(9, 9, 9)


def test_three_or_more_reviewed_due_cards_are_worth_a_nudge():
    n = decide([due_cards(1, 4)])
    assert n["title"] == "🐾 4 cards are ready" and "1 min" in n["body"]
    assert decide([due_cards(1, 2)]) is None and decide([due_cards(0, 10)]) is None


def test_at_most_one_a_day_never_in_quiet_hours_and_off_means_off():
    books = [due_cards(1, 5)]
    h = nudges.default_history()
    h["lastSentDay"] = "today"
    assert decide(books, h) is None and decide(books, hour=23) is None
    assert decide(books, s=settings(enabled=False)) is None
    assert decide(books, s=settings(pausedUntil=NOW + 1)) is None


def test_backs_off_after_two_ignored_nudges_and_goes_weekly_when_away():
    books = [due_cards(1, 5)]
    h = nudges.default_history()
    gentle_sent(h, NOW - 2 * DAY, "a")
    gentle_sent(h, NOW - DAY, "b")
    gentle_sent(h, NOW - DAY / 2, "c")
    assert h["ignoredInARow"] == 2 and decide(books, h) is None
    nudges.engaged(h, NOW - 1)
    assert h["ignoredInARow"] == 0
    gone = nudges.default_history()
    gone["lastEngaged"] = NOW - 8 * DAY
    gentle_sent(gone, NOW - 3 * DAY, "a")
    assert decide(books, gone, s=settings(sillySounds=False)) is None
    done = nudges.default_history()
    done["lastEngaged"] = NOW - 8 * DAY
    nudges.sent(done, {"mood": "shocked", "step": DEFAULTS[2]}, NOW - 3 * DAY, "a")
    assert decide(books, done)["mood"] == "gentle"


def test_silly_steps_dont_count_toward_the_usual_back_off():
    h = nudges.default_history()
    h["lastEngaged"] = NOW - 30 * HOUR
    gentle_sent(h, NOW - 30 * HOUR + 1, "a")
    for i, s in enumerate(DEFAULTS):
        nudges.sent(h, {"mood": s["sound"], "step": s}, NOW - (3 - i) * HOUR, "today")
    assert h["ignoredInARow"] == 0 and h["lastSentDay"] == "a" and h["lastStepId"] == DEFAULTS[2]["id"]
    assert decide([due_cards(1, 4)], h)["mood"] == "gentle"


def test_a_half_done_chapter_gets_a_loose_yarn_nudge_only_when_fully_prepared():
    p = progress.empty()
    p["loop"]["2"] = {"prime": NOW - DAY, "read": NOW - DAY}
    n = decide([(titled({2: "Caching"}), p)])
    assert n["title"] == "🧶 Loose yarn in “Caching”"
    assert n["body"] == "Next: recall it in your own words. Pip saved your spot."
    p["loop"]["2"] = {"prime": NOW - 1000}
    assert decide([(titled({2: "Caching"}), p)]) is None
    p["loop"] = {"1": {"prime": NOW - DAY, "read": NOW - DAY}}
    assert decide([(titled({1: "Caching"}, {"study": "done", "audio": "working"}), p)]) is None
    assert decide([(titled({1: "Caching"}, {"study": "done", "video": "failed"}), p)])["title"].startswith(
        "🧶"
    )


def test_the_longer_youre_away_the_sillier_pip_gets():
    books = [due_cards(1, 4)]
    assert [s["sound"] for s in DEFAULTS] == ["sadViolin", "sadMeow", "shocked"]
    assert [decide(books, away(h))["mood"] for h in (5, 9, 15, 25)] == [
        "gentle",
        "sadViolin",
        "sadMeow",
        "shocked",
    ]
    assert decide(books, nudges.default_history())["mood"] == "gentle"


def test_each_step_comes_once_per_absence_and_opening_the_app_starts_over():
    books = [due_cards(1, 4)]
    h = away(9, DEFAULTS[0])
    h["lastSentDay"] = "today"
    assert decide(books, h) is None
    assert decide(books, away(13, DEFAULTS[0]))["mood"] == "sadMeow"
    assert decide(books, away(25, DEFAULTS[1]))["mood"] == "shocked"
    h = away(30, DEFAULTS[2])
    h["lastSentDay"] = "today"
    assert decide(books, h) is None
    back = nudges.default_history()
    back["lastEngaged"] = NOW - 40 * HOUR
    nudges.sent(back, {"mood": "shocked", "step": DEFAULTS[2]}, NOW - 15 * HOUR, "yesterday")
    nudges.engaged(back, NOW - 9 * HOUR)
    assert decide(books, back)["mood"] == "sadViolin"


def test_silly_nudges_skip_the_one_a_day_limit_but_never_quiet_hours():
    books = [due_cards(1, 4)]
    h = away(9)
    h["lastSentDay"] = "today"
    assert decide(books, h)["mood"] == "sadViolin"
    assert decide(books, away(9), hour=23) is None
    assert decide(books, away(13))["mood"] == "sadMeow"
    gentle_after = away(9, DEFAULTS[0])
    gentle_sent(gentle_after, NOW - 1, "today")
    assert decide(books, gentle_after) is None


def test_steps_can_be_retimed_reused_removed_and_kept_in_order():
    books = [due_cards(1, 4)]
    only = settings([nudges.step("shocked", 2)])
    assert (
        decide(books, away(3), s=only)["mood"] == "shocked"
        and decide(books, away(1), s=only)["mood"] == "gentle"
    )
    late, early = nudges.step("sadViolin", 4), nudges.step("sadViolin", 1)
    two = settings([late, early])
    assert decide(books, away(1.5), s=two)["step"] == early
    assert decide(books, away(4.5, early), s=two)["step"] == late
    assert decide(books, away(30), s=settings([]))["mood"] == "gentle"


def test_the_last_step_can_repeat_every_few_hours():
    books = [due_cards(1, 4)]
    every_six = settings(DEFAULTS, repeat=6)
    h = nudges.default_history()
    h["lastEngaged"] = NOW - 29 * HOUR
    nudges.sent(h, {"mood": "shocked", "step": DEFAULTS[2]}, NOW - 5 * HOUR, "today")
    h["lastSentDay"] = "today"
    assert decide(books, h, s=every_six) is None
    h["lastSillySent"] = NOW - 6 * HOUR
    assert decide(books, h, s=every_six)["mood"] == "shocked"
    assert decide(books, h) is None and decide(books, h, hour=23, s=every_six) is None


def test_a_silly_nudge_still_says_whats_ready():
    books = [due_cards(1, 4)]
    violin = decide(books, away(9))
    assert violin["title"] == "🎻 Pip is playing a tiny sad violin"
    assert violin["body"] == "4 cards are ready. About 1 min with Pip, then you're done for today."
    shocked = decide(books, away(25))
    assert shocked["title"] == "😱 FAHHH! A whole day?!" and shocked["body"].startswith("4 cards are ready.")
    assert decide(books, away(3), s=settings([nudges.step("shocked", 2)]))["title"] == "😱 FAHHH! 3 hours?!"
    assert decide(books, away(75), s=settings([nudges.step("shocked", 72)]))["title"] == "😱 FAHHH! 3 days?!"
    assert decide(books, away(5))["title"] == "🐾 4 cards are ready"


def test_with_nothing_due_silly_mode_says_hi_at_most_once_a_week():
    nothing = [(titled({1: "Caching"}), progress.empty())]
    assert decide(nothing, away(5)) is None
    n = decide(nothing, away(15))
    assert (
        n["mood"] == "sadMeow"
        and n["missesYou"]
        and n["body"] == "Pip's ready when you are. Even five minutes counts."
    )
    h = away(15)
    nudges.sent(h, n, NOW - 3 * DAY, "earlier")
    assert h["lastMissedYou"] == NOW - 3 * DAY and decide(nothing, h) is None
    h["lastMissedYou"] = NOW - 8 * DAY
    assert decide(nothing, h)["missesYou"]
    assert decide([], away(15)) is None
    assert not decide([due_cards(1, 4)], h)["missesYou"]


def test_steps_due_together_play_one_after_another_and_edits_keep_the_ladder():
    books = [due_cards(1, 4)]
    violin, meow = nudges.step("sadViolin", 6), nudges.step("sadMeow", 6)
    same = settings([violin, meow])
    assert decide(books, away(7), s=same)["step"] == violin
    assert decide(books, away(7, violin), s=same)["step"] == meow
    both = away(7, violin)
    nudges.sent(both, {"mood": "sadMeow", "step": meow}, NOW - 1, "x")
    assert decide(books, both, s=same)["mood"] == "gentle"
    s = settings(list(DEFAULTS))
    h = away(13, nudges.ladder(s)[1])
    assert decide(books, h, s=s)["mood"] == "gentle"
    s["steps"].insert(0, nudges.step("shocked", 2))
    assert decide(books, h, s=s)["mood"] == "gentle"
    s["steps"] = [x for x in s["steps"] if x["sound"] != "sadMeow"]
    assert decide(books, h, s=s)["mood"] == "gentle"


def test_no_silly_nudge_when_the_clock_goes_back_or_neuralloop_is_in_front():
    h = nudges.default_history()
    h["lastEngaged"] = NOW + 30 * HOUR
    assert nudges.silly_step(settings(), h, NOW) is None
    assert decide([due_cards(1, 4)], h)["mood"] == "gentle"
    assert decide([due_cards(1, 4)], away(25), app_active=True)["mood"] == "gentle"
    assert (
        decide([due_cards(1, 4)], away(25), s=settings(sillySounds=False))["title"] == "🐾 4 cards are ready"
    )


def test_adding_a_step_picks_a_free_hour():
    assert nudges.free_hours(DEFAULTS) == 28 and nudges.free_hours([]) == 8
    assert nudges.free_hours([nudges.step("sadViolin", 4), nudges.step("sadMeow", 8)]) == 12
    assert nudges.free_hours([nudges.step("shocked", 168)]) == 167
    assert nudges.free_hours([nudges.step("shocked", h) for h in (166, 167, 168)]) == 165


def test_settings_saved_before_steps_keep_what_they_had():
    old = nudges.parse_settings({"enabled": True, "quietStart": 21, "quietEnd": 9, "pausedUntil": 0})
    assert old["quietStart"] == 21 and old["sillySounds"] and old["bigPip"] and old["volume"] == 0.8
    assert [s["sound"] for s in old["steps"]] == ["sadViolin", "sadMeow", "shocked"]
    assert [s["sound"] for s in nudges.parse_settings({"fahhh": False})["steps"]] == ["sadViolin", "sadMeow"]
    odd = nudges.parse_settings(
        {"steps": [{"sound": "gentle", "hours": 3}, {"sound": "sadMeow", "hours": 900}], "repeatHours": -4}
    )
    assert [s["sound"] for s in odd["steps"]] == ["sadMeow"] and odd["steps"][0]["hours"] == 168
    assert odd["repeatHours"] == 0
    twins = nudges.parse_settings(
        {
            "steps": [
                {"sound": "sadViolin", "hours": 5},
                {"sound": "sadMeow", "hours": 5},
                {"sound": "shocked", "hours": 168},
                {"sound": "sadMeow", "hours": 168},
            ]
        }
    )
    assert [s["hours"] for s in twins["steps"]] == [5, 6, 168, 167]
    broken = nudges.parse_settings({"steps": "nope", "quietStart": 20})
    assert broken["quietStart"] == 20 and [s["sound"] for s in broken["steps"]] == [
        "sadViolin",
        "sadMeow",
        "shocked",
    ]
    assert not nudges.parse_settings({"enabled": False})["enabled"]
    h = nudges.parse_history({"lastSent": "x", "lastMood": "loud", "lastEngaged": 7})
    assert h["lastEngaged"] == 7 and h["lastSent"] == 0 and h["lastMood"] is None


def test_every_mood_has_a_sample_and_silly_nudges_split_into_emoji_and_words():
    for mood in nudges.MOODS:
        assert nudges.sample(mood)["mood"] == mood
    assert nudges.sample("shocked")["title"] == "😱 FAHHH! A whole day?!"
    assert nudges.sample("gentle")["title"] == "🐾 Hi from Pip"
    violin = nudges.sample("sadViolin")
    assert nudges.emoji(violin) == "🎻" and nudges.words(violin) == "Pip is playing a tiny sad violin"
    plain = nudges.nudge("No emoji here", "")
    assert nudges.emoji(plain) == "" and nudges.words(plain) == "No emoji here"


def test_the_big_pip_only_shows_when_nothing_else_is_going_on():
    s = settings()
    calm: dict = {}
    assert nudges.shows_big_pip("sadViolin", s, calm) and not nudges.shows_big_pip("gentle", s, calm)
    assert not nudges.shows_big_pip("shocked", settings(bigPip=False), calm)
    for busy in ({"screenLocked": True}, {"fullScreenInFront": True}, {"microphoneInUse": True}):
        assert not nudges.shows_big_pip("shocked", s, busy)
        assert nudges.player("shocked", s, busy, test=False) == "notification"
        assert nudges.player("shocked", s, busy, test=True) == "app"
    assert nudges.player("sadViolin", s, calm, test=False) == "bigPip"
    assert nudges.player("sadMeow", settings(bigPip=False), calm, test=True) == "app"
    assert nudges.player("gentle", s, calm, test=True) == "notification"
    assert not nudges.needs_moment("gentle", s) and nudges.needs_moment("sadMeow", s)


def test_turning_notifications_off_means_nothing_at_all():
    books = [due_cards(1, 4)]
    off = settings(enabled=False)
    assert decide(books, away(25), s=off) is None
    assert not any(nudges.allows(off, k) for k in ("chapterReady", "nudges", "silly"))
    assert decide(books, away(5), s=settings(nudges=False)) is None
    s = settings(chapterReady=False)
    assert not nudges.allows(s, "chapterReady") and nudges.allows(s, "nudges")
    q = settings()
    assert nudges.is_quiet(q, NOW, 23) and nudges.is_quiet(q, NOW, 7) and not nudges.is_quiet(q, NOW, 12)
    q["pausedUntil"] = NOW + 1
    assert nudges.is_quiet(q, NOW, 12) and not nudges.is_quiet(q, NOW + 1, 12)
