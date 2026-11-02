"""The library's background work: one run per book, allowance checks never alongside a run, and a loop that
keeps going whatever one step does."""

import threading
import time
from pathlib import Path
from typing import ClassVar

import pytest
from neuralloop_desktop.app import runner
from neuralloop_desktop.app.library import Library
from neuralloop_desktop.core import prep


class FakeRun:
    started: ClassVar[list] = []

    def start(self, arguments, log, on_line, on_exit):
        time.sleep(0.05)  # long enough for a second caller to arrive
        FakeRun.started.append(arguments)

    def stop(self):
        pass


@pytest.fixture
def library(monkeypatch, tmp_path):
    monkeypatch.setenv("NEURALLOOP_HOME", str(tmp_path))
    FakeRun.started = []
    monkeypatch.setattr(runner, "Run", FakeRun)
    return Library()


def test_two_starts_at_once_make_one_run(library):
    """Checking that the book is free and claiming it are one step: two runs never start on one book."""
    win = prep.EVERYTHING
    threads = [threading.Thread(target=library.prepare, args=("book", Path("b.pdf"), win)) for _ in range(5)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len(FakeRun.started) == 1 and "book" in library.state.runs


def test_a_run_waits_for_an_allowance_check_already_underway(library, monkeypatch):
    """Every NotebookLM command rotates Google's cookie: a check and a run never overlap."""
    checking, finish = threading.Event(), threading.Event()
    order = []

    def once(arguments, timeout=60, stdin=None):
        checking.set()
        finish.wait(5)
        order.append("checked")
        return 0, []

    monkeypatch.setattr(runner, "once", once)
    monkeypatch.setattr(library, "entries", lambda: [])
    check = threading.Thread(target=library.refresh_usage, kwargs={"force": True})
    check.start()
    assert checking.wait(5)
    start = threading.Thread(target=library.prepare, args=("book", Path("b.pdf"), prep.EVERYTHING))
    start.start()
    time.sleep(0.2)
    assert FakeRun.started == []  # still waiting for the check
    finish.set()
    check.join()
    start.join()
    assert order == ["checked"] and len(FakeRun.started) == 1


def test_no_allowance_check_while_a_run_is_claimed(library, monkeypatch):
    asked = []
    monkeypatch.setattr(runner, "once", lambda arguments, timeout=60, stdin=None: asked.append(1) or (0, []))
    monkeypatch.setattr(library, "entries", lambda: [])  # a new book: not on the shelf yet
    library.prepare("book", Path("b.pdf"), prep.EVERYTHING)
    library.refresh_usage(force=True)
    assert asked == []


def test_at_launch_unfinished_books_resume_before_the_first_allowance_check(library, monkeypatch):
    order = []
    monkeypatch.setattr(library, "refresh", lambda: order.append("refresh"))
    monkeypatch.setattr(library, "resume_unfinished", lambda: order.append("resume"))
    monkeypatch.setattr(library, "refresh_usage", lambda force=False: order.append("usage"))
    library._first_look()
    assert order == ["refresh", "resume", "usage"]


def test_one_step_failing_never_stops_the_background_loop(library, monkeypatch):
    done = []

    def broken(*args, **kwargs):
        raise RuntimeError("a bad book")

    for name in ("refresh", "resume_unfinished", "refresh_usage"):
        monkeypatch.setattr(library, name, broken)
    monkeypatch.setattr(library, "nudge_tick", lambda: done.append("nudged"))
    library._first_look()  # nothing escapes
    library._tick(75)
    assert done == ["nudged"]  # the steps after a broken one still run
