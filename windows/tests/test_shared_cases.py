"""The cases the Swift core's tests run too (testdata/core): FSRS, progress merging, the prep window and
nudges."""

import json
from pathlib import Path

import pytest
from neuralloop_desktop.core import book as books
from neuralloop_desktop.core import loop, nudges, prep, progress

CASES = Path(__file__).resolve().parents[2] / "testdata" / "core"


def cases(name: str) -> list:
    data = json.loads((CASES / name).read_text(encoding="utf-8"))
    return [pytest.param(case, id=case["name"]) for case in data["cases"]]


@pytest.mark.parametrize("case", cases("fsrs.json"))
def test_fsrs(case):
    card = case["card"]
    for step in case["steps"]:
        card = loop.grade(card, step["rating"], step["now"])
    expect = case["expect"]
    assert card["s"] == pytest.approx(expect["s"], rel=1e-9, abs=1e-9)
    assert card["d"] == pytest.approx(expect["d"], rel=1e-9, abs=1e-9)
    assert (card["reps"], card["last"], card["due"]) == (expect["reps"], expect["last"], expect["due"])


@pytest.mark.parametrize("case", cases("progress-merge.json"))
def test_progress_merge(case):
    devices = [progress.normalize(d) for d in case["devices"]]
    got = progress.merged_same_device(*devices) if case["sameDevice"] else progress.merged(devices)
    assert got == progress.normalize(case["expect"])


@pytest.mark.parametrize("case", cases("prep-window.json"))
def test_prep_window(case):
    book = books.parse(case["book"]) if case["book"] is not None else None
    win = prep.window(book, progress.normalize(case["progress"]), case["everything"])
    has_work = win.has_work(book) if book else None
    assert {"chapters": win.chapters_spec, "media": win.media_spec, "hasWork": has_work} == case["expect"]


@pytest.mark.parametrize("case", cases("nudges.json"))
def test_nudges(case):
    pairs = [(books.parse(b["book"]), progress.normalize(b["progress"])) for b in case["books"]]
    got = nudges.decide(
        pairs,
        nudges.parse_settings(case["settings"]),
        nudges.parse_history(case["history"]),
        case["now"],
        case["hour"],
        case["today"],
        case["appActive"],
    )
    expect = case["expect"]
    assert (None if got is None else {k: got[k] for k in ("title", "body", "mood")}) == expect
