"""Loop.swift, FSRS.swift, Cards.swift, AutoSteps.swift: the same cases as the Swift tests."""

import math

from neuralloop_desktop.core import loop, progress

from .conftest import chapter

DAY = loop.DAY_MS
TWO = [chapter(1, cards=1), chapter(2, cards=1)]


def test_new_cards_follow_fsrs_starting_stability():
    assert round(loop.grade(None, 3, 0)["due"] / DAY) == 4
    assert round(loop.grade(None, 4, 0)["due"] / DAY) == 14


def test_again_brings_a_card_back_in_ten_minutes():
    reviewed = loop.grade(loop.grade(None, 3, 0), 1, 5 * DAY)
    assert reviewed["due"] - 5 * DAY == 10 * 60_000
    assert reviewed["reps"] == 2


def test_remembering_on_schedule_grows_the_interval():
    first = loop.grade(None, 3, 0)
    second = loop.grade(first, 3, first["due"])
    assert second["due"] - first["due"] > first["due"]


def test_matches_the_swift_and_javascript_schedulers_exactly():
    second = loop.grade(loop.grade(None, 3, 0), 3, 4 * DAY)
    assert abs(second["s"] - 14.808100506496405) < 1e-9
    assert abs(second["d"] - 5.1236762) < 1e-9
    assert second["due"] / DAY == 19
    lapse = loop.grade(second, 1, second["due"] + 2 * DAY)
    assert abs(lapse["s"] - 3.208136884166) < 1e-9
    assert abs(lapse["d"] - 6.8260892378) < 1e-9


def test_a_review_dated_before_the_last_one_counts_as_no_time_elapsed():
    first = loop.grade(None, 3, 10 * DAY)
    early = loop.grade(first, 3, 9 * DAY)
    same = loop.grade(first, 3, 10 * DAY)
    assert all(math.isfinite(early[k]) for k in ("s", "d", "due"))
    assert abs(early["s"] - same["s"]) < 1e-9 and early["s"] >= first["s"]
    lapse = loop.grade(first, 1, 9 * DAY)
    assert math.isfinite(lapse["s"]) and lapse["s"] >= 0.1


def test_the_loop_moves_through_five_steps_and_reports_closing_once():
    p = progress.empty()
    assert loop.next_stage(p, 1) == "prime"
    assert [loop.complete(p, 1, s, 1) for s in loop.STAGES] == [False, False, False, False, True]
    assert loop.next_stage(p, 1) is None
    assert loop.complete(p, 1, "space", 2) is False


def test_chapter_two_unlocks_only_after_chapter_one_is_closed():
    p = progress.empty()
    assert loop.is_unlocked(p, TWO, 1) and not loop.is_unlocked(p, TWO, 2)
    for s in loop.STAGES:
        loop.complete(p, 1, s, 1)
    assert loop.is_unlocked(p, TWO, 2)


def test_locked_chapters_cards_stay_out_of_review():
    p = progress.empty()
    assert [c["id"] for c in loop.due_cards(TWO, p, 0)] == ["1:0"]
    p["cards"]["1:0"] = loop.grade(None, 3, 0)
    assert loop.due_cards(TWO, p, 0) == []
    assert [c["id"] for c in loop.due_cards(TWO, p, 5 * DAY)] == ["1:0"]


def test_a_chapters_ideas_join_the_map_once_mapped():
    p = progress.empty()
    assert not loop.is_mapped(p, 1)
    loop.complete(p, 1, "map", 3)
    assert loop.is_mapped(p, 1)


def test_the_quiz_counts_as_recall_once_every_question_is_answered():
    p = progress.empty()
    c = chapter(1, quiz=3)
    assert not loop.quiz_finished(p, c)
    progress.set_quiz(p, "1", {"i": 2, "results": [True, False]}, 1)
    assert not loop.quiz_finished(p, c)
    progress.set_quiz(p, "1", {"i": 3, "results": [True, False, True]}, 2)
    assert loop.quiz_finished(p, c)
    assert not loop.quiz_finished(p, chapter(1))


def test_remember_is_done_when_every_card_has_been_reviewed_once():
    p = progress.empty()
    c = chapter(2, cards=2)
    assert not loop.cards_all_seen(p, c)
    p["cards"]["2:0"] = loop.grade(None, 1, 5)
    assert not loop.cards_all_seen(p, c) and loop.cards_seen(p, c) == 1
    p["cards"]["2:1"] = {"s": 0, "d": 0, "reps": 0, "last": 9, "due": 0}
    assert loop.cards_all_seen(p, c)
    p["cards"]["2:1"] = {"s": 0, "d": 0, "reps": 0, "last": 0, "due": 0}
    assert not loop.cards_all_seen(p, c)
    assert not loop.cards_all_seen(p, chapter(2))


def test_a_step_completes_itself_only_in_an_open_chapter_and_only_once():
    p = progress.empty()
    assert loop.complete_if_open(p, TWO, 2, "read", 1) is None
    assert "2" not in p["loop"]
    assert loop.complete_if_open(p, TWO, 1, "read", 5) is False
    assert loop.complete_if_open(p, TWO, 1, "read", 9) is None
    assert p["loop"]["1"]["read"] == 5
    for s in ("prime", "recall", "map"):
        loop.complete_if_open(p, TWO, 1, s, 10)
    assert loop.complete_if_open(p, TWO, 1, "space", 11) is True
    assert loop.complete_if_open(p, TWO, 9, "read", 12) is None


def test_a_checked_recall_answer_counts_only_when_its_a_real_try():
    assert not loop.is_real_answer("")
    assert not loop.is_real_answer("idk")
    assert not loop.is_real_answer("a s d f")
    assert loop.is_real_answer("Caches keep recent data close to the processor.")


def test_playing_and_reading_never_touch_updated_at():
    p = progress.empty()
    p["updatedAt"] = 7
    loop.record_play(p, 1, "audio", 0, 1, 1, 1)
    loop.credit_reading(p, 1, [0], 1, 2, True)
    assert p["updatedAt"] == 7
    assert p["watch"]["1"]["audio"] == [[0, 1]]
    assert p["reading"]["1"]["pages"] == {"0": 1}


def test_quiz_state_reads_leniently_and_eighty_percent_is_great():
    assert loop.quiz_state(None) == {"i": 0, "results": []}
    assert loop.quiz_state({"i": -3, "results": [True, "x"]}) == {"i": 0, "results": [True, False]}
    assert loop.quiz_is_great({"i": 5, "results": [True, True, True, True, False]}, 5)
    assert not loop.quiz_is_great({"i": 5, "results": [True, True, True, False, False]}, 5)
