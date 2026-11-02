"""What the window may load, where the library lives, and runs that can't start."""

import http.client
import json
import subprocess
import sys
from pathlib import Path
from typing import ClassVar

import pytest
from neuralloop_books import portable
from neuralloop_desktop.app import paths, runner, server
from neuralloop_desktop.app.api import Api
from neuralloop_desktop.app.server import Server


@pytest.fixture
def book(tmp_path, monkeypatch):
    monkeypatch.setenv("NEURALLOOP_HOME", str(tmp_path / "home"))
    folder = paths.books() / "my-book"
    for name, data in {
        "media/01-podcast.m4a": b"a" * 10,
        "media/01-video.mp4": b"v" * 10,
        "chapters/01.pdf": b"%PDF-1.4",
        "chapters/img/01-01.png": b"png",
        "chapters/img/evil.svg": b"<svg onload='alert(1)'/>",
        "chapters/page.html": b"<script>alert(1)</script>",
        "book.json": b"{}",
        "media/.hidden/01.m4a": b"a",
        "media/.secret.m4a": b"a",
        "chapters/.pages/01-0000.png": b"png",
    }.items():
        path = folder / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    return folder


def get(srv: Server, path: str) -> tuple[int, dict]:
    connection = http.client.HTTPConnection("127.0.0.1", srv.port, timeout=10)
    connection.request("GET", path, headers={"Host": f"127.0.0.1:{srv.port}"})
    answer = connection.getresponse()
    answer.read()
    return answer.status, dict(answer.getheaders())


def test_a_books_files_are_served_only_as_media_pictures_and_pdfs(book):
    srv = Server()
    srv.start()
    try:
        allowed = ("media/01-podcast.m4a", "media/01-video.mp4", "chapters/01.pdf", "chapters/img/01-01.png")
        for name in allowed:
            assert get(srv, f"/{srv.token}/book/my-book/{name}")[0] == 200, name
        for name in ("chapters/img/evil.svg", "chapters/page.html", "book.json"):  # active content, data
            assert get(srv, f"/{srv.token}/book/my-book/{name}")[0] == 404, name
        for name in ("media/.hidden/01.m4a", "media/.secret.m4a", "chapters/.pages/01-0000.png"):
            assert get(srv, f"/{srv.token}/book/my-book/{name}")[0] == 404, name  # dot-files at any level
    finally:
        srv.stop()


def test_every_answer_carries_the_windows_content_security_policy(book):
    srv = Server()
    srv.start()
    try:
        for path in ("ui/index.html", "ui/pip.html", "book/my-book/media/01-podcast.m4a"):
            status, headers = get(srv, f"/{srv.token}/{path}")
            policy = headers["Content-Security-Policy"]
            assert status == 200 and "default-src 'none'" in policy and "script-src 'self'" in policy
            assert "'unsafe-eval'" not in policy and "script-src 'self' 'unsafe-inline'" not in policy
    finally:
        srv.stop()


def test_the_windows_pages_run_no_inline_script():
    """script-src 'self': every script is a file of its own; no inline <script> or on…= handlers."""
    import re

    for page in paths.ui().glob("*.html"):
        html = page.read_text(encoding="utf-8")
        assert not re.search(r"<script(?![^>]*\bsrc=)[^>]*>", html), page.name
        assert not re.search(r"\son[a-z]+\s*=", html), page.name


def test_the_reading_pdf_must_be_inside_the_book(book, monkeypatch):
    class Session:
        folder = book
        progress: ClassVar[dict] = {"reading": {}}

        def chapter(self, n):
            return {"read": {"kind": "pdf", "file": "../../../outside.pdf"}}

    api = Api.__new__(Api)
    monkeypatch.setattr(api, "_session", lambda book_id: Session(), raising=False)
    looked = []
    monkeypatch.setattr("neuralloop_desktop.app.api.pdf_words", lambda pdf: looked.append(pdf) or [10])
    assert api.reading_plan("my-book", 1) is None
    assert looked == []


def test_a_run_whose_program_wont_start_closes_its_log(tmp_path, monkeypatch):
    opened = []
    real_open = open

    def tracking_open(path, mode="r", *args, **kwargs):
        handle = real_open(path, mode, *args, **kwargs)
        opened.append(handle)
        return handle

    def refuse(*args, **kwargs):
        raise OSError(2, "No such file")

    monkeypatch.setattr("builtins.open", tracking_open)
    monkeypatch.setattr(runner.subprocess, "Popen", refuse)
    monkeypatch.setattr(runner, "command", lambda: ["missing.exe"])
    with pytest.raises(OSError):
        runner.Run().start([], tmp_path / "pipeline.log", lambda line: None, lambda code, tail: None)
    assert opened and all(handle.closed for handle in opened)


def test_on_a_mac_the_windows_app_never_uses_the_mac_apps_library(monkeypatch, tmp_path):
    monkeypatch.delenv("NEURALLOOP_HOME", raising=False)
    monkeypatch.setattr(portable, "WINDOWS", False)
    monkeypatch.setattr(paths.sys, "platform", "darwin")
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    folder = paths.home()
    assert folder != portable.app_data() and "app.neuralloop.books" not in folder.parts
    assert folder.name == "NeuralLoop for Windows (development)"


def test_on_windows_the_library_is_in_local_app_data(monkeypatch, tmp_path):
    monkeypatch.delenv("NEURALLOOP_HOME", raising=False)
    monkeypatch.setattr(portable, "WINDOWS", True)
    monkeypatch.setattr(paths.sys, "platform", "win32")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Local"))
    assert paths.home() == tmp_path / "Local" / "NeuralLoop"


def test_a_library_from_the_roaming_folder_moves_to_the_local_one_once(monkeypatch, tmp_path):
    monkeypatch.delenv("NEURALLOOP_HOME", raising=False)
    monkeypatch.setattr(portable, "WINDOWS", True)
    monkeypatch.setattr(paths.sys, "platform", "win32")
    monkeypatch.setenv("APPDATA", str(tmp_path / "Roaming"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Local"))
    old = tmp_path / "Roaming" / "NeuralLoop"
    (old / "books" / "a").mkdir(parents=True)
    (old / "books" / "a" / "book.json").write_text("{}")
    (old / "ai.json").write_text(json.dumps({"engine": "auto"}))
    assert paths.move_old_library() is True
    new = tmp_path / "Local" / "NeuralLoop"
    assert (new / "books" / "a" / "book.json").exists() and (new / "ai.json").exists()
    assert not old.exists()
    assert paths.move_old_library() is False  # nothing left to move


def test_a_local_library_already_there_is_never_overwritten(monkeypatch, tmp_path):
    monkeypatch.delenv("NEURALLOOP_HOME", raising=False)
    monkeypatch.setattr(portable, "WINDOWS", True)
    monkeypatch.setattr(paths.sys, "platform", "win32")
    monkeypatch.setenv("APPDATA", str(tmp_path / "Roaming"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Local"))
    (tmp_path / "Roaming" / "NeuralLoop" / "books").mkdir(parents=True)
    (tmp_path / "Local" / "NeuralLoop" / "books" / "b").mkdir(parents=True)
    assert paths.move_old_library() is False
    assert (tmp_path / "Roaming" / "NeuralLoop" / "books").exists()


def test_stopping_a_run_elsewhere_uses_system32s_taskkill(monkeypatch, tmp_path):
    from neuralloop_desktop.app import library

    (tmp_path / ".running").write_text("4242")
    monkeypatch.setattr(portable, "WINDOWS", True)
    monkeypatch.setattr(portable, "is_locked", lambda path: True)
    ran = []
    monkeypatch.setattr(subprocess, "run", lambda argv, **kw: ran.append(argv))
    library.stop_run_elsewhere(tmp_path)
    assert ran == [[portable.taskkill(), "/T", "/F", "/PID", "4242"]]


def test_server_module_has_no_html_or_svg_for_books():
    assert (
        ".html" not in server.BOOK_TYPES
        and ".svg" not in server.BOOK_TYPES
        and ".json" not in server.BOOK_TYPES
    )
    assert sys.modules["neuralloop_desktop.app.server"] is server
