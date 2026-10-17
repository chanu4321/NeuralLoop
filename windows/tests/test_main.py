"""The installed programs: NeuralLoop.exe is the app, nl-book.exe the pipeline."""

import sys

import pytest
from neuralloop_desktop import main as entry
from neuralloop_desktop.app import runner


@pytest.fixture
def installed(monkeypatch, tmp_path):
    def as_program(name: str):
        exe = tmp_path / name
        exe.write_bytes(b"")
        monkeypatch.setattr(sys, "frozen", True, raising=False)
        monkeypatch.setattr(sys, "executable", str(exe))
        return exe

    return as_program


@pytest.fixture
def pipeline_calls(monkeypatch):
    calls = []

    def fake_main():
        calls.append(list(sys.argv))
        return 0

    monkeypatch.setattr("neuralloop_books.cli.main", fake_main)
    return calls


def test_nl_book_runs_the_pipeline_without_a_flag(installed, pipeline_calls):
    installed("nl-book.exe")
    assert entry.main(["book.pdf", "--out", "x"]) == 0
    assert pipeline_calls == [["neuralloop", "book.pdf", "--out", "x"]]


def test_nl_book_still_takes_the_flag(installed, pipeline_calls):
    installed("NL-BOOK.EXE")
    entry.main(["--pipeline", "--account"])
    assert pipeline_calls == [["neuralloop", "--account"]]


def test_the_app_is_not_the_pipeline(installed, monkeypatch, pipeline_calls):
    installed("NeuralLoop.exe")
    opened = []
    monkeypatch.setattr(entry, "run_app", lambda background=False: opened.append(background) or 7)
    assert entry.main([]) == 7
    assert entry.main(["--background"]) == 7
    assert opened == [False, True]
    assert pipeline_calls == []


def test_installed_app_runs_nl_book_next_to_it(installed):
    app = installed("NeuralLoop.exe")
    (app.parent / "nl-book.exe").write_bytes(b"")
    assert runner.command() == [str(app.parent / "nl-book.exe"), "--pipeline"]


def test_from_the_repo_it_runs_nl_book_py():
    command = runner.command()
    assert command[0] == sys.executable
    assert command[1].replace("\\", "/").endswith("pipeline/nl_book.py")


def test_the_pipeline_always_writes_utf8(installed, monkeypatch):
    """The app reads nl-book.exe's output as UTF-8; a console code page (cp1252) can't even write ✓."""
    import io

    raw = io.BytesIO()
    console = io.TextIOWrapper(raw, encoding="cp1252", errors="strict")
    monkeypatch.setattr(sys, "stdout", console)

    def progress():
        print("  ✓ chapter 1 quiz (0s)")
        return 0

    monkeypatch.setattr("neuralloop_books.cli.main", progress)
    installed("nl-book.exe")
    assert entry.main(["--dry-run"]) == 0
    sys.stdout.flush()
    assert "✓ chapter 1".encode() in raw.getvalue()
