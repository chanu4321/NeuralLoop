"""book.json: the payload the pipeline writes for every book (Book.swift).

Every part may be missing or null while a book is still being prepared, so everything is read with a default.
The result is plain dicts in book.json's own shape (the window draws them as they are), defaults filled in.
"""

import json
from pathlib import Path
from typing import Any

from .jsonish import integer, number, text

STATUSES = {"todo", "working", "done", "skipped", "failed", "waiting_quota"}


def _list(value: Any) -> list:
    return value if isinstance(value, list) else []


def _dict(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def _optional(value: Any) -> str | None:
    return value if isinstance(value, str) else None


def _mind(node: Any) -> dict | None:
    if not isinstance(node, dict) or not isinstance(node.get("name"), str):
        return None
    return {
        "name": node["name"],
        "children": [c for c in (_mind(x) for x in _list(node.get("children"))) if c],
    }


def _reading(value: Any) -> dict:
    value = _dict(value)
    if value.get("kind") == "pdf" and isinstance(value.get("file"), str):
        return {"kind": "pdf", "file": value["file"]}
    return {"kind": "text", "text": text(value.get("text"))}


def _quiz(q: Any) -> dict | None:
    q = _dict(q)
    options = [o for o in _list(q.get("options")) if isinstance(o, str)]
    answer = integer(q.get("a"))
    if not isinstance(q.get("q"), str) or not options or answer is None:
        return None
    why = [w if isinstance(w, str) else "" for w in _list(q.get("why"))]
    return {"q": q["q"], "options": options, "a": answer, "hint": text(q.get("hint")), "why": why}


def _tour(value: Any) -> list[dict]:
    steps = []
    for s in _list(value):
        if isinstance(s, dict) and isinstance(s.get("title"), str):
            ids = [i for i in _list(s.get("nodeIds")) if isinstance(i, str)]
            steps.append(
                {"title": s["title"], "description": _optional(s.get("description")), "nodeIds": ids}
            )
    return steps


def _concept_graph(value: Any) -> dict | None:
    if not isinstance(value, dict):
        return None
    keys = ("id", "name", "type", "summary", "detail", "complexity", "layer")
    concepts = [
        c for c in _list(value.get("concepts")) if isinstance(c, dict) and isinstance(c.get("id"), str)
    ]
    edges = [
        e
        for e in _list(value.get("edges"))
        if isinstance(e, dict) and isinstance(e.get("source"), str) and isinstance(e.get("target"), str)
    ]
    return {
        "concepts": [{k: text(c.get(k)) for k in keys} for c in concepts],
        "layers": [
            {"id": text(x.get("id")), "name": text(x.get("name"))}
            for x in _list(value.get("layers"))
            if isinstance(x, dict)
        ],
        "edges": [
            {
                "source": e["source"],
                "target": e["target"],
                "type": text(e.get("type")),
                "description": _optional(e.get("description")),
            }
            for e in edges
        ],
        "tour": _tour(value.get("tour")),
    }


def _explainer(value: Any) -> dict | None:
    if not isinstance(value, dict):
        return None
    slides = []
    for s in _list(value.get("slides")):
        if isinstance(s, dict):
            slides.append(
                {
                    "title": text(s.get("title")),
                    "points": [p for p in _list(s.get("points")) if isinstance(p, str)],
                    "narration": text(s.get("narration")),
                    "pose": text(s.get("pose")),
                    "audio": _optional(s.get("audio")),
                    "duration": number(s.get("duration")),
                }
            )
    return {"slides": slides}


def chapter(raw: Any) -> dict | None:
    raw = _dict(raw)
    n = integer(raw.get("n"))
    if n is None:
        return None
    return {
        "n": n,
        "title": text(raw.get("title")),
        "read": _reading(raw.get("read")),
        "status": {k: v for k, v in _dict(raw.get("status")).items() if v in STATUSES},
        "notes": {k: v for k, v in _dict(raw.get("notes")).items() if isinstance(v, str)},
        "guide": [
            {
                "section": text(g.get("section")),
                "level": text(g.get("level"), "normal"),
                "why": text(g.get("why")),
            }
            for g in _list(raw.get("guide"))
            if isinstance(g, dict)
        ],
        "recall": [
            {"prompt": r["prompt"], "keyPoints": [k for k in _list(r.get("keyPoints")) if isinstance(k, str)]}
            for r in _list(raw.get("recall"))
            if isinstance(r, dict) and isinstance(r.get("prompt"), str)
        ],
        "quiz": [q for q in (_quiz(x) for x in _list(raw.get("quiz"))) if q],
        "cards": [
            {"front": c["front"], "back": text(c.get("back"))}
            for c in _list(raw.get("cards"))
            if isinstance(c, dict) and isinstance(c.get("front"), str)
        ],
        "mindmap": _mind(raw.get("mindmap")),
        "graph": _concept_graph(raw.get("graph")),
        "audio": _optional(raw.get("audio")),
        "transcript": _optional(raw.get("transcript")),
        "video": _optional(raw.get("video")),
        "explainer": _explainer(raw.get("explainer")),
    }


def knowledge_graph(raw: Any) -> dict:
    """The book map. A repeated idea id keeps its first idea; links and tour stops to missing ideas go."""
    raw = _dict(raw)
    seen: set[str] = set()
    nodes = []
    for node in _list(raw.get("nodes")):
        if isinstance(node, dict) and isinstance(node.get("id"), str) and node["id"] not in seen:
            seen.add(node["id"])
            extra = ("summary", "detail", "type", "complexity", "layer", "layerName")
            nodes.append(
                {
                    "id": node["id"],
                    "name": text(node.get("name"), node["id"]),
                    **{k: _optional(node.get(k)) for k in extra},
                    "chapter": integer(node.get("chapter")),
                }
            )
    return _graph(nodes, _list(raw.get("edges")), _tour(raw.get("tour")))


def _graph(nodes: list[dict], edges: list, tour: list[dict]) -> dict:
    ids = {n["id"] for n in nodes}
    kept = [e for e in edges if isinstance(e, dict) and e.get("source") in ids and e.get("target") in ids]
    steps = ({**s, "nodeIds": [i for i in s["nodeIds"] if i in ids]} for s in tour)
    return {
        "nodes": nodes,
        "edges": [
            {
                "source": e["source"],
                "target": e["target"],
                "type": _optional(e.get("type")),
                "description": _optional(e.get("description")),
            }
            for e in kept
        ],
        "tour": [s for s in steps if s["nodeIds"]],
    }


def only_chapters(graph: dict, chapters: set[int]) -> dict:
    """Only the ideas from these chapters, the links between them, and tour steps that still have ideas."""
    return _graph([n for n in graph["nodes"] if n.get("chapter") in chapters], graph["edges"], graph["tour"])


def chapter_graph(graph: dict, n: int, chapter_tour: list[dict]) -> dict:
    """One chapter's concept graph with its own guided tour (ids carry the "cN:" prefix in the book map)."""
    part = only_chapters(graph, {n})
    tour = [{**s, "nodeIds": [f"c{n}:{i}" for i in s["nodeIds"]]} for s in chapter_tour]
    return _graph(part["nodes"], part["edges"], tour)


def parse(raw: Any) -> dict:
    raw = _dict(raw)
    return {
        "title": text(raw.get("title"), "Your book") or "Your book",
        "source": text(raw.get("source")),
        "dryRun": raw.get("dryRun") is True,
        "engine": text(raw.get("engine"), "notebooklm"),
        "model": text(raw.get("model")),
        "chapters": [c for c in (chapter(x) for x in _list(raw.get("chapters"))) if c],
        "graph": knowledge_graph(raw.get("graph")),
    }


def from_book_data(script: str) -> dict | None:
    """book-data.js as the old pipeline wrote it: `window.BOOK = <payload>;` (read as data, never run)."""
    body = script.strip().removeprefix("window.BOOK = ").removesuffix(";")
    try:
        return parse(json.loads(body))
    except json.JSONDecodeError:
        return None


def load(folder: Path) -> dict | None:
    """A folder's book.json, or the book-data.js of books made before the app (only without book.json)."""
    try:
        return parse(json.loads((folder / "book.json").read_bytes()))
    except FileNotFoundError:
        pass
    except (OSError, ValueError):
        return None
    try:
        return from_book_data((folder / "book-data.js").read_text(encoding="utf-8"))
    except OSError:
        return None


def file_in(folder: Path, relative: str | None) -> Path | None:
    """A file the book points at, only if it's inside the book's folder (BookFiles.url)."""
    if not relative or relative.startswith("/") or "\\" in relative or ":" in relative or "\x00" in relative:
        return None
    root = folder.resolve()
    try:
        path = (folder / relative).resolve()
    except OSError:
        return None
    return path if path != root and root in path.parents else None
