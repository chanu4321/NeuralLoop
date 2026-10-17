"""Builders shared by the tests: chapters and books in book.json's (parsed) shape."""

from neuralloop_desktop.core import book


def chapter(
    n: int, title: str = "", cards: int = 0, quiz: int = 0, status: dict | None = None, **extra
) -> dict:
    raw = {
        "n": n,
        "title": title,
        "cards": [{"front": f"f{i}", "back": f"b{i}"} for i in range(cards)],
        "quiz": [{"q": "?", "options": ["a", "b"], "a": 0} for _ in range(quiz)],
        "status": status or {},
        **extra,
    }
    return book.chapter(raw)


def make_book(chapters: list[dict], engine: str = "auto", title: str = "Book") -> dict:
    return {
        "title": title,
        "source": "",
        "dryRun": False,
        "engine": engine,
        "model": "",
        "chapters": chapters,
        "graph": {"nodes": [], "edges": [], "tour": []},
    }


ALL_DONE = {k: "done" for k in ("study", "graph", "quiz", "cards", "mindmap", "audio", "video")}
