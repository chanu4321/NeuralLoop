"""What the window can ask for (pywebview's js_api): `window.pywebview.api.<name>(...)` in the page.

Every method returns plain JSON. Rules stay in `core`; this only gathers, calls, and shapes. Push updates go
the other way through `emit` (the shelf changed, a progress line, a message)."""

import contextlib
import json
import subprocess
import sys
import threading
import webbrowser
from pathlib import Path

from neuralloop_books import portable

from ..core import aiconfig, coverage, loop, nudges, pipeline_run, prep, study
from ..core.book import file_in as books_file_in
from . import keys, paths, runner
from .library import Library
from .session import Session

LINK_SCHEMES = ("http://", "https://")


class Api:
    def __init__(self, library: Library, base_url: str):
        self._library = library
        self._base = base_url
        self._sessions: dict[str, Session] = {}
        self._lock = threading.Lock()
        self._windows: dict = {}
        self._sign_in_cancel: threading.Event | None = None
        self._events: list | None = None

    # Plumbing (names starting with _ are never exposed to the page).

    def _attach(self, name: str, window) -> None:
        self._windows[name] = window

    def _session(self, book_id: str) -> Session | None:
        if not pipeline_run.is_valid_id(book_id):
            return None
        with self._lock:
            session = self._sessions.get(book_id)
            if session is None:
                folder = paths.books() / book_id
                if not folder.is_dir():
                    return None
                session = Session(folder, on_step=self._library.study_moved)
                self._sessions[book_id] = session
            session.reload_book()
            return session

    def _forget(self, book_id: str) -> None:
        with self._lock:
            session = self._sessions.pop(book_id, None)
        if session:
            session.flush()

    def _flush_all(self) -> None:
        for session in list(self._sessions.values()):
            session.flush()

    # The shelf.

    def shelf(self) -> dict:
        return {**self._library.shelf(), "base": self._base, "windows": portable.WINDOWS}

    def add_book(self) -> bool:
        window = self._windows.get("main")
        if window is None:
            return False
        import webview

        chosen = window.create_file_dialog(
            webview.OPEN_DIALOG, allow_multiple=True, file_types=("Books (*.pdf;*.epub)", "All files (*.*)")
        )
        for path in chosen or []:
            self._library.add(path)
        return bool(chosen)

    def add_paths(self, files: list) -> int:
        added = 0
        for path in files or []:
            if isinstance(path, str) and self._library.add(path):
                added += 1
        return added

    def add_sample(self) -> bool:
        return self._library.add_sample()

    def prepare_more(self, book_id: str) -> None:
        self._library.prepare_more(book_id)

    def make_with_my_ai(self, book_id: str) -> None:
        self._library.make_with_my_ai(book_id)

    def remove_book(self, book_id: str) -> None:
        self._forget(book_id)
        self._library.remove_book(book_id)

    def show_in_folder(self, book_id: str) -> None:
        if not pipeline_run.is_valid_id(book_id):
            return
        folder = paths.books() / book_id
        if portable.WINDOWS:
            subprocess.Popen(["explorer", str(folder)], **portable.no_window())
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(folder)])
        else:
            subprocess.Popen(["xdg-open", str(folder)])

    def open_link(self, url: str) -> None:
        """Links in a chapter open in the browser; anything else is ignored."""
        if isinstance(url, str) and url.lower().startswith(LINK_SCHEMES):
            webbrowser.open(url)

    def problem(self, book_id: str) -> dict | None:
        with self._library.lock:
            return self._library.state.problems.get(book_id)

    # One book.

    def book(self, book_id: str) -> dict | None:
        """Everything the book screen draws: the book as book.json says, progress, and per-chapter state."""
        session = self._session(book_id)
        if not session:
            return None
        b, p = session.book, session.progress
        entry = next((e for e in self._library.entries() if e["id"] == book_id), None)
        activity = entry["activity"] if entry else None
        chapters = []
        for c in b["chapters"]:
            n = c["n"]
            chapters.append(
                {
                    "n": n,
                    "unlocked": loop.is_unlocked(p, b["chapters"], n),
                    "closed": loop.is_closed(p, n),
                    "next": loop.next_stage(p, n),
                    "steps": {s: s in loop.steps(p, n) for s in loop.STAGES},
                    "ahead": prep.is_ahead(c),
                    "ready": c["status"].get("study") == "done",
                    "complete": prep.is_complete(c),
                    "quiz": session.quiz(n),
                    "remake": session.remake(n),
                    "cardsSeen": loop.cards_seen(p, c),
                    "due": len(session.due(n)),
                }
            )
        mapped = {c["n"] for c in b["chapters"] if loop.is_mapped(p, c["n"])}
        return {
            "id": book_id,
            "book": b,
            "chapters": chapters,
            "last": p["last"],
            "mapPos": p["mapPos"],
            "mapSeen": p["mapSeen"],
            "bookMap": {"mapped": sorted(mapped)},
            "preparing": bool(entry and entry["preparing"]),
            "line": entry["lastLine"] if entry else "",
            "activity": self._activity(activity),
            "usage": self._library.usage,
            "labels": loop.LABELS,
            "watch": p["watch"],
            "reading": p["reading"],
            "dueAll": len(session.due()),
            "base": self._base,
        }

    def _activity(self, activity: dict | None) -> dict | None:
        if not activity or activity.get("ended"):
            return None
        now = study_now()
        items = []
        for item in activity["items"]:
            measured = prep.item_progress(item, now)
            items.append(
                {"n": item["n"], "item": item["item"], **measured, "percent": prep.percent_text(measured)}
            )
        queue = [
            {"n": q["n"], "item": q["item"], "place": prep.place_text(i)}
            for i, q in enumerate(activity["queue"])
        ]
        return {"items": items, "queue": queue}

    def reading_plan(self, book_id: str, n: int) -> dict | None:
        """A chapter's "pages" for reading time: ~300-word sections of text, or the PDF's pages, with what
        each needs (max(6 s, its words at 600 a minute))."""
        session = self._session(book_id)
        chapter = session.chapter(n) if session else None
        if not chapter:
            return None
        read = chapter["read"]
        if read["kind"] == "text":
            blocks = [b.strip() for b in read["text"].split("\n\n") if b.strip()]
            sections = coverage.sections(blocks)
            needs = [coverage.needed(sum(coverage.words(blocks[i]) for i in s)) for s in sections]
            return {
                "kind": "text",
                "blocks": blocks,
                "sections": sections,
                "needs": needs,
                "done": coverage.reading_progress(session.progress["reading"].get(str(n)), needs),
            }
        pdf = session.folder / read["file"]
        words = pdf_words(pdf)
        needs = [coverage.needed(w) for w in words]
        return {
            "kind": "pdf",
            "file": read["file"],
            "pages": len(words),
            "needs": needs,
            "done": coverage.reading_progress(session.progress["reading"].get(str(n)), needs),
        }

    def transcript(self, book_id: str, relative: str) -> dict:
        session = self._session(book_id)
        path = books_file_in(session.folder, relative) if session else None
        try:
            data = json.loads(path.read_bytes()) if path else {}
        except (OSError, ValueError):
            data = {}
        lines = [x for x in data.get("lines", []) if isinstance(x, dict)] if isinstance(data, dict) else []
        return {"lines": lines, "complete": data.get("complete", True) if isinstance(data, dict) else True}

    def complete(self, book_id: str, n: int, stage: str) -> dict:
        session = self._session(book_id)
        if not session or stage not in loop.STAGES:
            return {}
        return {"closed": session.complete(int(n), stage)}

    def remember(self, book_id: str, n: int, stage: str) -> None:
        session = self._session(book_id)
        if session and stage in loop.STAGES:
            session.remember(int(n), stage)

    def set_quiz(self, book_id: str, n: int, i: int, results: list) -> dict | None:
        session = self._session(book_id)
        return session.set_quiz(int(n), int(i), list(results)) if session else None

    def check_recall(self, book_id: str, n: int, index: int, answer: str) -> dict:
        session = self._session(book_id)
        return session.check_recall(int(n), int(index), str(answer)) if session else {}

    def remake_draft(self, book_id: str, n: int, guess: str) -> None:
        session = self._session(book_id)
        if session:
            session.set_remake_draft(int(n), str(guess))

    def check_remake(self, book_id: str, n: int, guess: str) -> dict:
        session = self._session(book_id)
        return session.check_remake(int(n), str(guess)) if session else {}

    def place_on_map(self, book_id: str, placed: dict, seen: list) -> None:
        session = self._session(book_id)
        if session:
            session.place_on_map(placed or {}, seen or [])

    def due_cards(self, book_id: str, n: int | None = None) -> list:
        session = self._session(book_id)
        if not session:
            return []
        return [
            {**c, "front": study.plain_math(c["card"]["front"]), "back": study.plain_math(c["card"]["back"])}
            for c in session.due(None if n is None else int(n))
        ]

    def review(self, book_id: str, card_id: str, rating: str) -> dict | None:
        session = self._session(book_id)
        return session.review(str(card_id), str(rating)) if session else None

    def record_play(
        self,
        book_id: str,
        n: int,
        kind: str,
        start: float,
        end: float,
        rate: float,
        wall: float,
        length: float,
    ) -> dict | None:
        session = self._session(book_id)
        if not session:
            return None
        return session.record_play(
            int(n), kind, float(start), float(end), float(rate), float(wall), float(length or 0)
        )

    def credit_reading(
        self, book_id: str, n: int, visible: list, seconds: float, needs: list, earning: bool
    ) -> dict | None:
        session = self._session(book_id)
        if not session:
            return None
        return session.credit_reading(
            int(n), [int(v) for v in visible], float(seconds), [float(x) for x in needs], bool(earning)
        )

    def tick(self, book_id: str, seconds: float) -> None:
        """15 s of study with this book in front; studying counts as a visit (no silly nudges about being
        away)."""
        session = self._session(book_id)
        if session:
            session.tick(float(seconds))
            self._library.engaged()

    def close_book(self, book_id: str) -> None:
        session = self._sessions.get(book_id)
        if session:
            session.flush()

    # Being here.

    def active(self, active: bool) -> None:
        """The window came to the front or left it: both count as a visit, and nothing silly comes
        meanwhile."""
        self._library.app_active = bool(active)
        self._library.engaged()

    # Settings: your AI.

    def ai_settings(self) -> dict:
        try:
            config = aiconfig.parse(json.loads(paths.ai_config().read_bytes()))
        except (OSError, ValueError):
            config = aiconfig.defaults()
        from neuralloop_books.speech.kokoro import VOICES

        saved = {name: bool(value) for name, value in keys.all_keys().items()}
        make = aiconfig.matching(config["make"]) if config["make"]["provider"] != "auto" else None
        recall = aiconfig.matching(config["recall"])
        return {
            "config": config,
            "engines": aiconfig.ENGINES,
            "presets": aiconfig.PRESETS,
            "makePreset": make["id"] if make else None,
            "recallPreset": recall["id"] if recall else "ollama",
            "keysSaved": saved,
            "keysPersistent": keys.persistent(),
            "voices": VOICES,
            "prepareEverything": self._library.prepare_everything,
            "ollama": runner.find_ollama() is not None,
        }

    def save_ai(self, choices: dict) -> dict:
        """Settings → Your AI. Keys go to Credential Manager; everything else to ai.json."""
        current = self.ai_settings()["config"]
        engine = choices.get("engine", current["engine"])
        make_id = choices.get("makePreset")
        config = dict(current, engine=engine if engine in aiconfig.ENGINES else "auto")
        config["make"] = (
            aiconfig.choice_for(make_id, choices.get("makeModel"), choices.get("makeBaseUrl"))
            if make_id
            else {"provider": "auto"}
        )
        if choices.get("recallPreset"):
            config["recall"] = aiconfig.choice_for(
                choices["recallPreset"], choices.get("recallModel"), choices.get("recallBaseUrl")
            )
        voices = choices.get("voices")
        if isinstance(voices, list) and len(voices) == 2:
            config["voices"] = voices
        for key in ("voiceQuality", "audioLength"):
            if key in choices:
                config[key] = choices[key]
        if "hermesTools" in choices:
            config["hermesTools"] = bool(choices["hermesTools"])
        target = paths.ai_config()
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(".tmp")
        tmp.write_bytes(aiconfig.encode(config))
        portable.replace(tmp, target)
        for name, value in (choices.get("keys") or {}).items():
            if name in pipeline_run.KEY_NAMES and isinstance(value, str) and value:
                keys.save(name, value)
        if "prepareEverything" in choices:
            self._library.settings.set("prepareEverything", bool(choices["prepareEverything"]))
        self._library.settings_changed()
        return self.ai_settings()

    def forget_key(self, name: str) -> dict:
        if name in pipeline_run.KEY_NAMES:
            keys.save(name, "")
            self._library.settings_changed()
        return self.ai_settings()

    def check_ai(self) -> dict:
        """Save and test: `--check-ai` for the book maker, each item's own model, and the recall model."""
        _, lines = runner.once(["--check-ai"], timeout=300)
        for line in reversed(lines):
            if report := aiconfig.parse_check(line):
                return report
        return {"make": {"ok": False, "message": (lines[-1] if lines else "Pip couldn't run the check.")}}

    def setup(self) -> dict:
        """First run of your own AI: start Ollama, download the local model and the voices."""
        lines: list[str] = []

        def heard(line: str) -> None:
            text = line.strip().removeprefix("setup:").strip()
            lines.append(text)
            self._emit("setup", text)

        code = runner.stream(["--setup"], heard)
        return {"ok": code == 0, "lines": lines[-6:]}

    # Settings: account (Google, for NotebookLM).

    def account(self) -> dict:
        _, lines = runner.once(["--account"], timeout=60)
        for line in reversed(lines):
            if line.startswith("Account: "):
                with contextlib.suppress(ValueError):
                    return json.loads(line[len("Account: ") :])
        return {"signedIn": False, "email": ""}

    def sign_in(self) -> dict:
        self._sign_in_cancel = threading.Event()
        lines: list[str] = []

        def heard(line: str) -> None:
            lines.append(line)
            if line.strip().startswith("setup:"):
                self._emit("signin", line.strip().removeprefix("setup:").strip())

        code = runner.stream(["--signin"], heard, cancel=self._sign_in_cancel)
        self._library.settings_changed()
        account = self.account()
        return {
            "ok": code == 0,
            "account": account,
            "cancelled": code == 130,
            "message": "" if code == 0 else (lines[-1] if lines else ""),
        }

    def cancel_sign_in(self) -> None:
        if self._sign_in_cancel:
            self._sign_in_cancel.set()

    def sign_out(self) -> dict:
        runner.once(["--signout"], timeout=60)
        return self.account()

    # Settings: nudges.

    def nudge_settings(self) -> dict:
        settings = self._library.nudge_settings()
        return {
            "settings": settings,
            "moods": nudges.MOOD_NAMES,
            "sounds": nudges.SILLY_SOUNDS,
            "freeHours": nudges.free_hours(settings["steps"]),
        }

    def save_nudges(self, changes: dict) -> dict:
        merged = {**self._library.nudge_settings(), **(changes or {})}
        self._library.settings.set("nudgeSettings", nudges.parse_settings(merged))
        return self.nudge_settings()

    def add_silly_step(self, sound: str) -> dict:
        settings = self._library.nudge_settings()
        if sound in nudges.SILLY_SOUNDS and len(settings["steps"]) < nudges.MOST_STEPS:
            settings["steps"].append(nudges.step(sound, nudges.free_hours(settings["steps"])))
            self._library.settings.set("nudgeSettings", settings)
        return self.nudge_settings()

    def test_nudge(self, mood: str) -> None:
        if mood in nudges.MOODS:
            self._library.send_nudge(nudges.sample(mood), test=True)

    def pause_until_tomorrow(self) -> None:
        self._library.pause_until_tomorrow()

    # Settings: the library.

    def library_info(self) -> dict:
        size = self._library.library_size()
        return {"bytes": size, "text": human_size(size), "folder": str(paths.home())}

    def remove_all_books(self) -> None:
        for book_id in list(self._sessions):
            self._forget(book_id)
        self._library.remove_all_books()

    def first_run(self) -> dict:
        settings = self._library.settings
        return {"done": bool(settings.get("firstRunDone", False))}

    def finish_first_run(self) -> None:
        self._library.settings.set("firstRunDone", True)

    # Windows of the app.

    def show_main(self, book_id: str | None = None) -> None:
        window = self._windows.get("main")
        if window:
            window.show()
            window.restore()
            if book_id:
                self._emit("open", book_id)

    def hide_big_pip(self) -> None:
        window = self._windows.get("pip")
        if window:
            window.hide()

    def hide_panel(self) -> None:
        panel = self._windows.get("panel")
        if panel:
            panel.hide()

    def _emit(self, name: str, data) -> None:
        if self._events is not None:  # development: the browser asks for events
            self._events.append(json.loads(json.dumps({"name": name, "data": data}, default=str)))
        payload = json.dumps({"name": name, "data": data}, default=str)
        for window in list(self._windows.values()):
            with contextlib.suppress(Exception):  # a window that's closing doesn't stop the others
                window.evaluate_js(f"window.NL && window.NL.event({payload})")


def study_now() -> float:
    import time

    return time.time() * 1000


def human_size(size: int) -> str:
    for unit in ("bytes", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "bytes" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} GB"


_PDF_WORDS: dict[tuple[str, float], list[int]] = {}


def pdf_words(pdf: Path) -> list[int]:
    """Words on each page of a chapter's PDF (what reading time needs); remembered per file version."""
    try:
        key = (str(pdf), pdf.stat().st_mtime)
    except OSError:
        return []
    if key in _PDF_WORDS:
        return _PDF_WORDS[key]
    try:
        from pypdf import PdfReader

        reader = PdfReader(str(pdf))
        words = [coverage.words(page.extract_text() or "") for page in reader.pages]
    except Exception:
        words = []
    _PDF_WORDS[key] = words
    return words
