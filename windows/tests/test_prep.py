"""ChapterReady, AutoResume, PrepWindow, RunProblemText, NotebookLMUsage: the Swift tests' cases."""

from neuralloop_desktop.core import book, prep, progress

MIN = 60_000.0
READY = {"study": "done", "quiz": "done", "audio": "done", "video": "done"}
NO_MEDIA = {"study": "done", "quiz": "done", "audio": "skipped", "video": "skipped"}
COMING = {"study": "done", "quiz": "done", "audio": "working", "video": "todo"}
ITEMS = ["study", "graph", "quiz", "cards", "mindmap", "audio", "video"]
ALL_STEPS = {"prime": 1, "read": 1, "recall": 1, "map": 1, "space": 1}


def status_book(chapters: list[dict], engine: str = "auto") -> dict:
    return book.parse(
        {
            "title": "B",
            "engine": engine,
            "chapters": [
                {"n": i + 1, "title": f"Chapter {i + 1}", "status": s} for i, s in enumerate(chapters)
            ],
        }
    )


def full_book(count: int, status: str = "done", overrides: dict | None = None) -> dict:
    overrides = overrides or {}
    return status_book(
        [{item: overrides.get(f"{n}:{item}", status) for item in ITEMS} for n in range(1, count + 1)]
    )


def closed(n: int, read_next: bool = False) -> dict:
    p = progress.empty()
    for k in range(1, n + 1):
        p["loop"][str(k)] = dict(ALL_STEPS)
    if read_next:
        p["loop"][str(n + 1)] = {"prime": 1, "read": 1}
    return p


def step(b, p, watching, announced=(), quiet=False):
    chapter, keep = prep.ready_step(b, p, set(watching), set(announced), quiet)
    return (chapter["n"] if chapter else None), keep


def test_the_chapter_you_can_study_is_announced_once_its_whole_loop_is_ready():
    n, w = step(status_book([COMING, READY]), progress.empty(), [])
    assert (n, w) == (None, {1})
    n, w = step(status_book([READY, READY]), progress.empty(), w)
    assert (n, w) == (1, set())
    assert step(status_book([READY, READY]), progress.empty(), w)[0] is None


def test_locked_or_already_ready_chapters_are_never_announced():
    _, w = step(status_book([COMING, COMING]), progress.empty(), [])
    assert step(status_book([COMING, READY]), progress.empty(), w) == (None, {1})
    assert step(status_book([READY, COMING]), progress.empty(), []) == (None, set())


def test_after_closing_a_loop_the_next_chapter_is_watched_and_announced():
    n, w = step(status_book([READY, COMING]), closed(1), [])
    assert (n, w) == (None, {2})
    assert step(status_book([READY, NO_MEDIA]), closed(1), w)[0] == 2


def test_waiting_items_hold_a_chapter_back_but_failed_ones_dont():
    assert not prep.is_complete(status_book([{"study": "done", "audio": "waiting_quota"}])["chapters"][0])
    assert not prep.is_complete(status_book([COMING])["chapters"][0])
    assert prep.is_complete(status_book([{"study": "done", "audio": "failed"}])["chapters"][0])
    assert prep.is_complete(status_book([NO_MEDIA])["chapters"][0])


def test_quiet_hours_hold_the_announcement_and_it_comes_once_after():
    _, w = step(status_book([COMING]), progress.empty(), [])
    assert step(status_book([READY]), progress.empty(), w, quiet=True) == (None, {1})
    assert step(status_book([READY]), progress.empty(), {1}, quiet=False) == (1, set())
    assert step(status_book([READY]), progress.empty(), {1}, announced=[1]) == (None, set())
    assert step(status_book([READY, READY]), closed(2), [1, 2]) == (None, set())


def test_the_alert_says_whats_ready_honestly():
    title, body = prep.ready_message(status_book([READY])["chapters"][0], "Caching")
    assert title == "Chapter 1 is ready to study"
    assert (
        body
        == "“Chapter 1” in Caching: everything is ready, podcast and video included. Pip saved you a spot."
    )
    assert prep.ready_message(status_book([NO_MEDIA])["chapters"][0], "Caching")[1] == (
        "“Chapter 1” in Caching: everything Pip is making for it is ready. Pip saved you a spot."
    )
    podcast = status_book([{"study": "done", "audio": "done", "video": "skipped"}])["chapters"][0]
    assert prep.ready_message(podcast, "Caching")[1].endswith(
        "everything is ready, podcast included. Pip saved you a spot."
    )
    failed = status_book([{"study": "done", "audio": "done", "video": "failed"}])["chapters"][0]
    assert "Prepare more tries again." in prep.ready_message(failed, "Caching")[1]


def test_setup_problems_wait_for_new_settings_and_other_failures_back_off():
    setup = prep.record_after(None, 3, 1000)
    assert not prep.may_start(setup, 0, 1000 + 600 * MIN) and prep.may_start(setup, 2000, 3000)
    assert not prep.may_start(prep.record_after(None, 2, 1000), 0, 1e9)
    once = prep.record_after(None, 1, 0)
    assert not prep.may_start(once, 0, 4 * MIN) and prep.may_start(once, 0, 5 * MIN)
    thrice = prep.record_after(prep.record_after(once, 1, 0), 1, 0)
    assert thrice["failuresInARow"] == 3 and not prep.may_start(thrice, 0, 19 * MIN)
    assert prep.record_after(thrice, 0, 0)["failuresInARow"] == 0 and prep.may_start(None, 0, 0)


def test_work_left_or_a_lifted_limit_means_there_is_work():
    def b(status, engine="auto"):
        return status_book([{"quiz": "done", "audio": status}], engine)

    assert prep.has_auto_work(b("todo"), prep.EVERYTHING, None, 0, 0)
    assert not prep.has_auto_work(b("done"), prep.EVERYTHING, None, 0, 0)
    assert not prep.has_auto_work(b("waiting_quota", "local"), prep.EVERYTHING, None, 0, 60 * MIN)
    assert prep.has_auto_work(b("waiting_quota", "local"), prep.EVERYTHING, None, 0, 361 * MIN)


def test_a_new_book_gets_chapter_one_whole_and_chapter_twos_quick_items():
    w = prep.window(full_book(10, "todo"), progress.empty(), False)
    assert (w.chapters_spec, w.media_spec) == ("1-2", "1")
    w = prep.window(None, progress.empty(), False)
    assert (w.chapters_spec, w.media_spec) == ("1-2", "1")


def test_finishing_reading_widens_the_window_and_it_stops_at_the_last_chapter():
    b = full_book(10)
    w = prep.window(b, closed(2), False)
    assert (w.chapters_spec, w.media_spec) == ("1-4", "1-3")
    w = prep.window(b, closed(2, read_next=True), False)
    assert (w.chapters_spec, w.media_spec) == ("1-5", "1-4")
    assert prep.window(full_book(3), closed(2, read_next=True), False).chapters_spec == "1-3"
    w = prep.window(full_book(3), closed(3), False)
    assert (w.chapters_spec, w.media_spec) == ("1-3", "1-3")
    w = prep.window(full_book(1), progress.empty(), False)
    assert (w.chapters_spec, w.media_spec) == ("1", "1")


def test_everything_and_media_items_only_for_media_chapters():
    w = prep.window(full_book(10), progress.empty(), True)
    assert w == prep.EVERYTHING and w.chapters_spec == "all" and w.media_spec == "all"
    assert prep.wants_everything(True, "1-2") and prep.wants_everything(False, "all")
    assert not prep.wants_everything(False, "1-2")
    w = prep.window(full_book(10), progress.empty(), False)
    assert w.includes(1, "video") and w.includes(2, "quiz")
    assert not w.includes(2, "audio") and not w.includes(3, "study") and prep.EVERYTHING.includes(99, "video")


def test_there_is_work_only_inside_the_window():
    start = prep.window(None, progress.empty(), False)
    assert not start.has_work(
        full_book(4, "done", {"3:quiz": "todo", "2:audio": "skipped", "4:study": "skipped"})
    )
    assert start.has_work(full_book(4, "done", {"2:quiz": "todo"}))
    assert start.has_work(full_book(4, "done", {"2:study": "skipped"}))
    assert start.has_work(full_book(4, "done", {"1:video": "skipped"}))
    assert not start.has_work(full_book(4, "done", {"1:video": "failed"}))
    assert start.has_work(full_book(4, "done", {"4:video": "working"}))
    later = full_book(4, "done", {"3:quiz": "todo"})
    assert not prep.has_auto_work(later, start, None, 0, 0) and prep.has_auto_work(
        later, prep.EVERYTHING, None, 0, 0
    )
    assert not prep.has_auto_work(full_book(4, "done", {"3:audio": "waiting_quota"}), start, None, 0, 1e12)
    assert prep.has_auto_work(full_book(4, "done", {"1:audio": "waiting_quota"}), start, None, 0, 1e12)


def test_a_run_ending_with_the_window_moved_starts_again():
    narrow, wider = prep.Window(2, 1), prep.Window(3, 2)
    assert prep.start_again(narrow, wider, 0, True)
    assert not prep.start_again(wider, wider, 0, True)
    assert not prep.start_again(narrow, wider, 0, False) and not prep.start_again(narrow, wider, 1, True)


def test_chapters_ahead_and_not_yet():
    b = full_book(3, "done", {"2:audio": "skipped", "3:study": "skipped"})
    assert [prep.is_ahead(c) for c in b["chapters"]] == [False, True, True]
    assert prep.not_yet("The podcast") == "The podcast: Pip will prepare this when you get close."


def test_an_automatic_runs_problem_says_what_helps():
    assert prep.run_problem(2) == "Pip couldn't read this book. Try a different PDF or EPUB copy."
    assert prep.run_problem(3).startswith("Pip needs a little setup first.")
    assert (
        prep.run_problem(1)
        == prep.run_problem(-9)
        == ("Pip hit a snag and will try again on its own in a little while.")
    )
    line = 'Invalid chapter selection "1-x". Use forms like 1-3, 1,4,7, all, or none.'
    assert prep.run_problem(2, ["Splitting…", line]).startswith("Pip got mixed up")


USAGE = (
    'NotebookLM usage: {"known": true, "available": true, "fiveHour": {"remaining": 55.9, "resetsAt": '
    '"2026-09-29T10:21:40.110085+00:00"}, "weekly": {"remaining": 90.2, "resetsAt": '
    '"2026-10-04T13:21:40.110172+00:00"}, "podcast": false, "video": true}'
)


def test_reads_notebooklm_usage_and_knows_what_it_can_make():
    usage = prep.parse_usage(USAGE)
    assert usage["known"] and usage["available"] and not usage["podcast"] and usage["video"]
    assert usage["fiveHour"]["remaining"] == 55.9
    assert prep.parse_usage('NotebookLM usage: {"known": false}')["known"] is False
    assert prep.parse_usage("nothing") is None
    assert (
        prep.can_make(usage, "video") and not prep.can_make(usage, "audio") and prep.can_make(usage, "quiz")
    )
