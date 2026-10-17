"""The app layer end to end, with no window: add the sample book as a practice run (the offline dry run),
watch the shelf, read files through the server, and study with a session."""

import http.client
import json
import time

import pytest
from neuralloop_desktop.app import keys, paths, runner
from neuralloop_desktop.app.api import Api
from neuralloop_desktop.app.library import Library, describe, outcome
from neuralloop_desktop.app.server import Server, contained
from neuralloop_desktop.core import pipeline_run


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("NEURALLOOP_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("NEURALLOOP_VIDEO", "0")  # an MP4 takes seconds; the rest of the run is what's tested
    for name in pipeline_run.KEY_NAMES:
        monkeypatch.delenv(name, raising=False)
    return tmp_path / "home"


def wait_for(check, seconds=120.0):
    deadline = time.time() + seconds
    while time.time() < deadline:
        if check():
            return True
        time.sleep(0.2)
    return False


@pytest.fixture
def prepared(home):
    """The sample book, prepared offline (practice voices and model)."""
    told = []
    library = Library(notify=lambda **kw: told.append(kw))
    assert library.add(str(paths.sample_book()), practice=True, wait=True)
    assert wait_for(lambda: not library.state.runs), "the practice run didn't finish"
    library.refresh()
    return library, told


def get(server: Server, path: str, headers: dict | None = None) -> tuple[int, dict, bytes]:
    connection = http.client.HTTPConnection("127.0.0.1", server.port, timeout=10)
    connection.request("GET", path, headers={"Host": f"127.0.0.1:{server.port}", **(headers or {})})
    answer = connection.getresponse()
    return answer.status, dict(answer.getheaders()), answer.read()


def test_a_practice_run_puts_the_book_on_the_shelf(prepared):
    library, _ = prepared
    shelf = library.shelf()
    assert len(shelf["books"]) == 1
    card = shelf["books"][0]
    assert card["id"] == "sample-book" and card["title"] and not card["preparing"]
    assert card["dots"][0] == "open" and card["madeWith"] == "A practice run"
    assert json.loads((paths.home() / "runs.json").read_text())["sample-book"]["exitCode"] == 0


def test_the_server_serves_only_the_books_own_files_with_ranges(prepared):
    library, _ = prepared
    server = Server()
    server.start()
    try:
        book = library.scanned["sample-book"].book
        audio = book["chapters"][0]["audio"]
        status, headers, body = get(
            server, f"/{server.token}/book/sample-book/{audio}", {"Range": "bytes=0-99"}
        )
        assert status == 206 and len(body) == 100 and headers["Content-Range"].startswith("bytes 0-99/")
        assert get(server, f"/{server.token}/book/sample-book/book.json")[0] == 200
        assert get(server, f"/{server.token}/assets/pip-poses.js")[2].startswith(b"window.PIP=")
        assert get(server, f"/{server.token}/ui/index.html")[0] == 200
        for bad in (
            "/nope/book/sample-book/book.json",
            f"/{server.token}/book/sample-book/../../runs.json",
            f"/{server.token}/book/sample-book/.running",
            f"/{server.token}/book/../settings.json",
            f"/{server.token}/book/sample-book/C:/Windows/win.ini",
        ):
            assert get(server, bad)[0] == 404, bad
        assert get(server, f"/{server.token}/ui/index.html", {"Host": "evil.example"})[0] == 403
    finally:
        server.stop()


def test_contained_never_leaves_its_folder(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "b.txt").write_text("x")
    assert contained(tmp_path, "a/b.txt") == (tmp_path / "a" / "b.txt").resolve()
    for bad in ("", "../x", "a/../../x", "/etc/passwd", "C:\\x", "a\\..\\..\\x", "a/b.txt\x00"):
        assert contained(tmp_path, bad) is None


def test_studying_through_the_api_completes_steps_and_saves(prepared):
    library, _ = prepared
    api = Api(library, "http://127.0.0.1:1/t")
    view = api.book("sample-book")
    first = view["chapters"][0]
    assert first["unlocked"] and not first["closed"] and first["next"] == "prime"
    assert not view["chapters"][1]["unlocked"]
    # The quiz finishes Recall; reviewing every card finishes Remember.
    quiz = view["book"]["chapters"][0]["quiz"]
    earned = api.set_quiz("sample-book", 1, len(quiz), [True] * len(quiz))
    assert earned and earned["stage"] == "recall"
    last = None
    for card in api.due_cards("sample-book", 1):
        last = api.review("sample-book", card["id"], "good") or last
    assert last and last["stage"] == "space"
    # Remaking the mind map from memory finishes Map.
    mind = view["book"]["chapters"][0]["mindmap"]
    guess = "\n".join(b["name"] for b in mind["children"])
    result = api.check_remake("sample-book", 1, guess)
    assert result["percent"] > 0 and result["earned"]["stage"] == "map"
    # Listening: most of the podcast played at a believable speed.
    done = None
    for second in range(0, 90):
        done = api.record_play("sample-book", 1, "audio", second, second + 1, 1, 1, 100) or done
    assert done and done["stage"] == "prime"
    # Reading: every section on screen long enough, to the last one.
    plan = api.reading_plan("sample-book", 1)
    assert plan["kind"] == "text" and plan["needs"]
    earned = None
    for page, need in enumerate(plan["needs"]):
        for _ in range(int(need / 2) + 1):
            earned = api.credit_reading("sample-book", 1, [page], 2, plan["needs"], True) or earned
    assert earned and earned["stage"] == "read" and earned["closed"]
    view = api.book("sample-book")
    assert view["chapters"][0]["closed"] and view["chapters"][1]["unlocked"]
    saved = json.loads((paths.books() / "sample-book" / "progress.json").read_text())
    assert set(saved["loop"]["1"]) >= {"prime", "read", "recall", "map", "space", "closedShown"}


def test_recall_falls_back_to_word_matching_when_no_model_answers(prepared, monkeypatch):
    library, _ = prepared
    monkeypatch.setattr(runner, "once", lambda *a, **k: (3, ["no model"]))
    api = Api(library, "http://x")
    prompt = api.book("sample-book")["book"]["chapters"][0]["recall"][0]
    answer = " ".join(prompt["keyPoints"])
    result = api.check_recall("sample-book", 1, 0, answer)
    assert result["by"] == "word match" and any(result["covered"]) and result["earned"]["stage"] == "recall"


def test_removing_a_book_takes_it_off_the_shelf(prepared):
    library, _ = prepared
    library.remove_book("sample-book")
    assert library.shelf()["books"] == []
    assert wait_for(lambda: not (paths.books() / "sample-book").exists(), 10)


def test_keys_never_reach_the_command_line_and_stay_in_memory_without_a_vault(home, monkeypatch):
    monkeypatch.setattr(keys, "_keyring", lambda: None)
    keys.save("OPENAI_API_KEY", " sk-test-123 ")
    assert keys.read("OPENAI_API_KEY") == "sk-test-123"
    env = runner.environment()
    assert env["OPENAI_API_KEY"] == "sk-test-123" and env["NEURALLOOP_HOME"] == str(home)
    keys.save("OPENAI_API_KEY", "")
    assert "OPENAI_API_KEY" not in runner.environment()
    with pytest.raises(ValueError):
        keys.save("PATH", "x")


def test_words_for_progress_lines_and_outcomes():
    assert describe(pipeline_run.parse_line("  ✓ chapter 2 audio (3s)")) == "Chapter 2: podcast ready"
    assert describe(pipeline_run.parse_line("  setup: downloading voices 40%")) == "Downloading voices 40%"
    assert outcome("Caching", 0, []) == "“Caching” is ready."
    assert outcome("Caching", 2, ["This book is already being prepared."]) is None
    assert outcome("Caching", 3, ["Set a key in Settings."]) == "Set a key in Settings."
    assert "pipeline.log" in outcome("Caching", 1, ["Traceback", "ValueError: nope"])
