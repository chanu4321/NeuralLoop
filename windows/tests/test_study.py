"""ReadingCredit, Remake, RecallCheck, Activity, Shelf, Book: the same cases as the Swift tests."""

import datetime as dt
import json
from pathlib import Path

from neuralloop_desktop.core import book, coverage, loop, progress, study

from .conftest import chapter

FIXTURE = Path(__file__).resolve().parents[2] / "pipeline" / "tests" / "fixtures" / "book.json"


def local(y, m, d, h=12) -> float:
    return dt.datetime(y, m, d, h).timestamp() * 1000


def test_a_page_needs_at_least_six_seconds_or_skimming_speed():
    assert [coverage.needed(w) for w in (0, 30, 300, 600)] == [6, 6, 30, 60]


def test_time_only_counts_while_someone_is_there_and_looking():
    assert coverage.earning(100, 50, True, True)
    assert not coverage.earning(200, 50, True, True)
    assert not coverage.earning(100, None, True, True)
    assert not coverage.earning(100, 99, False, True) and not coverage.earning(100, 99, True, False)


def test_seconds_are_shared_by_the_pages_on_screen():
    r = {"pages": {}, "count": 0, "last": None}
    assert not coverage.credit(r, [0], 1, 3, False) and r == {"pages": {}, "count": 0, "last": None}
    assert coverage.credit(r, [0, 1], 1, 3, True)
    assert r == {"pages": {"0": 0.5, "1": 0.5}, "count": 3, "last": 1}
    coverage.credit(r, [2], 600, 3, True)
    assert r["pages"]["2"] == 2 and r["last"] == 2
    assert not coverage.credit(r, [7, -1], 1, 3, True)


def test_flipping_through_faster_than_skimming_does_not_count():
    r = {"pages": {}, "count": 0, "last": None}
    needs = [coverage.needed(400)] * 10
    for page in range(10):
        for _ in range(5):
            coverage.credit(r, [page], 1, 10, True)
    got = coverage.reading_progress(r, needs)
    assert got["counted"] == 0 and got["reachedLast"] and not got["done"]


def test_reading_most_pages_and_reaching_the_end_is_done():
    r = {"pages": {}, "count": 0, "last": None}
    needs = [6.0] * 20
    for page in range(17):
        for _ in range(6):
            coverage.credit(r, [page], 1, 20, True)
    got = coverage.reading_progress(r, needs)
    assert got["counted"] == 17 and not got["reachedLast"] and not got["done"]
    coverage.credit(r, [19], 1, 20, True)
    got = coverage.reading_progress(r, needs)
    assert got["reachedLast"] and got["done"] and got["fraction"] == 0.85
    assert not coverage.reading_progress(None, [])["done"]


def test_text_is_split_into_sections_of_about_three_hundred_words():
    para = " ".join(["word"] * 120)
    blocks = ["# Title", para, para, para, "![a figure](img/01-01.png)", para, para]
    assert coverage.sections(blocks) == [[0, 1, 2, 3], [4, 5, 6]]
    assert coverage.words("Hello, *wide* world  —  ok") == 4
    assert coverage.sections([]) == []


def test_reading_round_trips_skips_bad_entries_and_merges_by_the_most():
    x = progress.normalize(
        json.loads('{"reading":{"3":{"pages":{"0":12.25,"1":"x","2":7},"count":30,"last":2},"4":"nope"}}')
    )
    assert (
        x["reading"]["3"] == {"pages": {"0": 12.25, "2": 7}, "count": 30, "last": 2}
        and "4" not in x["reading"]
    )
    assert progress.normalize(json.loads(progress.encode(x)))["reading"]["3"]["pages"]["0"] == 12.3
    mac = progress.normalize(json.loads('{"reading":{"1":{"pages":{"0":10,"1":3},"count":5,"last":1}}}'))
    pad = progress.normalize(json.loads('{"reading":{"1":{"pages":{"1":8,"4":6},"count":5,"last":4}}}'))
    m = progress.merged([mac, pad])
    assert m["reading"]["1"] == {"pages": {"0": 10, "1": 8, "4": 6}, "count": 5, "last": 4}


def test_names_match_across_word_forms_but_not_unrelated_words_or_single_letters():
    assert study.names_match("caching strategy", "Caching strategies")
    assert study.names_match("invalidation", "Cache invalidation")
    assert not study.names_match("networking", "Cache invalidation")
    assert not study.names_match("e", "Failure modes") and not study.names_match("mod", "Failure modes")
    assert study.names_match("MCP", "mcp")


def test_remaking_the_map_scores_branches_and_sub_ideas():
    mind = book.chapter(
        {
            "n": 1,
            "mindmap": {
                "name": "Caching",
                "children": [
                    {"name": "Foundations", "children": [{"name": "Key terms"}]},
                    {"name": "Failure modes"},
                ],
            },
        }
    )["mindmap"]
    result = study.compare("Foundations\n- key terms\n", mind)
    assert result["percent"] == 67
    assert result["rows"][0]["remembered"] and result["rows"][0]["children"][0]["remembered"]
    assert not result["rows"][1]["remembered"]
    assert study.compare("e", mind)["percent"] == 0


def test_latex_math_reads_as_plain_text():
    assert study.plain_math("The $M \\times N$ problem") == "The M × N problem"
    assert study.plain_math("costs $5 and $6") == "costs $5 and $6"
    assert study.plain_math("$O(n \\cdot m)$ and \\text{fast}") == "O(n · m) and fast"
    assert study.plain_math("no math here") == "no math here"


POINTS = ["the world keeps changing", "software is a snapshot", "you need monitoring"]


def test_word_matching_and_warm_feedback():
    assert study.word_match(POINTS, "Software is a snapshot and you need monitoring.") == [False, True, True]
    assert study.recall_feedback(POINTS, [True, False, False]).startswith(
        "Nice: you remembered that the world keeps changing."
    )
    assert study.recall_feedback(POINTS, [True] * 3) == "You covered every key point. Lovely recall!"
    assert study.recall_feedback(POINTS, [False] * 3) == (
        "Good start. Next time, try to include that the world keeps changing."
    )


def test_quitting_mid_tick_keeps_the_seconds_since_the_last_tick():
    assert study.partial_tick(100, 50, 109) == 9
    assert study.partial_tick(100, 105, 109) == 4
    assert study.partial_tick(100, None, 109) == 0
    assert study.partial_tick(100, 0, 200) == 15 and study.partial_tick(100, 0, 90) == 0


def test_study_time_is_logged_per_local_day_without_touching_updated_at():
    p = progress.empty()
    study.log_study(p, local(2026, 9, 28), 15)
    study.log_study(p, local(2026, 9, 28) + 60_000, 15)
    assert p["log"] == {"2026-09-28": 30} and p["updatedAt"] == 0


def test_the_year_grid_covers_53_weeks_ending_this_week_sunday_first():
    grid = study.year_grid({"2026-09-28": 1500, "2026-09-27": 300}, local(2026, 9, 28))
    assert len(grid["weeks"]) == 53 and all(len(w) == 7 for w in grid["weeks"])
    last = grid["weeks"][-1]
    assert last[0]["date"] == "2026-09-27" and last[1]["date"] == "2026-09-28"
    assert last[1]["level"] == 3 and last[0]["level"] == 1 and last[2]["future"]
    assert [study.level(s) for s in (0, 60, 540, 900, 1800, 5400)] == [0, 1, 1, 2, 3, 4]


def test_year_stats_are_only_encouraging():
    log = {"2026-09-24": 600, "2026-09-25": 1200, "2026-09-26": 3000, "2026-09-28": 60, "2024-01-01": 9999}
    s = study.year_stats(log, local(2026, 9, 28))
    assert s["total"] == 4860 and s["days"] == 4 and s["longestRun"] == 3
    assert s["best"] == {"date": "2026-09-26", "seconds": 3000}
    assert (study.format_duration(4860), study.format_duration(45), study.format_duration(0)) == (
        "1 h 21 min",
        "1 min",
        "0 min",
    )


def test_each_chapter_shows_where_it_is_on_the_shelf():
    p = progress.empty()
    for s in loop.STAGES:
        loop.complete(p, 1, s, 1)
    chapters = [chapter(n, status={"study": "done"} if n <= 3 else {}) for n in range(1, 5)]
    assert study.dots(chapters, p) == ["closed", "open", "ready", "preparing"]
    assert study.combined_log([{"a": 600, "b": 60}, {"a": 300}]) == {"a": 900, "b": 60}


def test_a_book_keeps_its_cover_colour_and_matches_the_mac():
    assert study.cover_index("MCP illustrated guidebook", 5) == study.cover_index(
        "MCP illustrated guidebook", 5
    )
    assert len({study.cover_index(c, 5) for c in "ABCDEF"}) > 1
    assert 0 <= study.cover_index("", 5) < 5
    # sum of scalar * (offset + 1): "AB" = 65*1 + 66*2 = 197
    assert study.cover_index("AB", 5) == 197 % 5


def test_decodes_what_the_pipeline_writes():
    b = book.parse(json.loads(FIXTURE.read_text()))
    assert b["title"] == "sample book" and len(b["chapters"]) == 4 and b["engine"] == "local"
    first = b["chapters"][0]
    assert first["status"]["quiz"] == "done" and len(first["quiz"]) >= 2 and len(first["cards"]) >= 3
    assert first["read"]["kind"] == "text" and first["read"]["text"]
    assert first["guide"][0]["level"] in ("deep", "normal", "skim") and first["recall"][0]["keyPoints"]
    assert first["mindmap"]["name"] and first["graph"]["concepts"]
    assert first["audio"].startswith("media/") and first["transcript"].endswith(".json")
    assert first["explainer"]["slides"][0]["audio"].startswith("media/")
    assert b["chapters"][2]["status"]["quiz"] == "skipped" and b["graph"]["nodes"]


def test_reads_book_data_from_books_made_before_the_app(tmp_path):
    text = FIXTURE.read_text()
    assert book.from_book_data("window.BOOK = " + text + ";\n") == book.parse(json.loads(text))
    assert book.from_book_data('  window.BOOK = {"title":"Old"}  ')["title"] == "Old"
    assert book.from_book_data('{"title":"Bare"};')["title"] == "Bare"
    assert book.from_book_data("window.BOOK = ;") is None and book.from_book_data("alert(1)") is None
    assert book.load(tmp_path) is None
    (tmp_path / "book-data.js").write_text('window.BOOK = {"title":"Old"};\n')
    assert book.load(tmp_path)["title"] == "Old"
    (tmp_path / "book.json").write_text('{"title":"New"}')
    assert book.load(tmp_path)["title"] == "New"
    (tmp_path / "book.json").write_text("not json")
    assert book.load(tmp_path) is None


def test_files_a_book_points_at_stay_inside_its_folder(tmp_path):
    (tmp_path / "media").mkdir()
    (tmp_path / "media" / "a.m4a").write_bytes(b"x")
    assert book.file_in(tmp_path, "media/a.m4a") == (tmp_path / "media" / "a.m4a").resolve()
    for bad in ("", "/etc/passwd", "../x", "media/../../x", "C:\\Windows\\win.ini", "\\\\server\\share"):
        assert book.file_in(tmp_path, bad) is None


def test_the_knowledge_graph_keeps_ids_unique_and_links_whole():
    g = book.knowledge_graph(
        {
            "nodes": [
                {"id": "a", "name": "A", "chapter": 1},
                {"id": "a", "name": "dup"},
                {"id": "b", "chapter": 2},
            ],
            "edges": [{"source": "a", "target": "b"}, {"source": "a", "target": "zz"}],
            "tour": [{"title": "t", "nodeIds": ["zz"]}, {"title": "u", "nodeIds": ["a", "zz"]}],
        }
    )
    assert [n["name"] for n in g["nodes"]] == ["A", "b"] and len(g["edges"]) == 1
    assert g["tour"] == [{"title": "u", "description": None, "nodeIds": ["a"]}]
    assert [n["id"] for n in book.only_chapters(g, {1})["nodes"]] == ["a"]
    assert book.only_chapters(g, {1})["edges"] == []


def test_reading_shows_how_far_each_page_is_while_you_read():
    """The step's bar moves with every second read, and each page shows its own share, before any page has
    had all the time it needs (a dense page needs 30 to 40 s)."""
    r = {"pages": {}, "count": 0, "last": None}
    needs = [40.0, 40.0, 20.0]
    for _ in range(10):
        coverage.credit(r, [0], 1, 3, True)
    got = coverage.reading_progress(r, needs)
    assert got["counted"] == 0 and got["pages"] == [0.25, 0.0, 0.0]
    assert got["time"] == 10 / 100
    for _ in range(25):
        coverage.credit(r, [2], 1, 3, True)  # more than page 3 needs: capped at its share
    got = coverage.reading_progress(r, needs)
    assert got["pages"] == [0.25, 0.0, 1.0] and got["time"] == 30 / 100 and got["counted"] == 1
    empty = coverage.reading_progress(None, [])
    assert empty["pages"] == [] and empty["time"] == 0
