"""The shelf (Library.swift): books in the library folder, adding a book (which starts the pipeline), live
progress, and the background loop that keeps it all current: resuming unfinished books just ahead of the
reader, NotebookLM's usage, "chapter ready" notifications, and Pip's nudges.

Thread-safe: the window's bridge, pipeline runs, and the background loop all call in."""

import contextlib
import datetime as dt
import json
import shutil
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from neuralloop_books import portable

from ..core import book as books
from ..core import loop, nudges, pipeline_run, prep, progress, study
from . import paths, runner
from .store import JsonFile

ITEM_NAMES = {
    "study": "reading guide",
    "graph": "concept map",
    "quiz": "quiz",
    "cards": "flashcards",
    "mindmap": "mind map",
    "audio": "podcast",
    "video": "video",
}


def now_ms() -> float:
    return time.time() * 1000


def describe(line: dict) -> str | None:
    """Plain words for a progress line, for the book card."""
    kind = line["kind"]
    name = ITEM_NAMES.get(line.get("item", ""), line.get("item", ""))
    if kind == "added":
        return f"Reading chapter {line['chapter']}…"
    if kind == "made":
        return f"Chapter {line['chapter']}: {name} ready"
    if kind == "fellBack":
        return f"Chapter {line['chapter']}: making the {name} with {line['to']}"
    if kind == "waiting":
        return f"Chapter {line['chapter']}: {name} will be made later"
    if kind == "failed":
        return f"Chapter {line['chapter']}: the {name} needs another try"
    if kind == "setup":
        return line["text"][:1].upper() + line["text"][1:]
    if kind == "finished":
        return "All set"
    return line.get("text") or None


def outcome(title: str, code: int, tail: list[str]) -> str | None:
    """What to say when a run ends (Library.outcome)."""
    if code == 0:
        return f"“{title}” is ready."
    if any("already being prepared" in t for t in tail):
        return None
    reason = next((t for t in reversed(tail) if not t.startswith(('File "', "^", "Traceback"))), "")
    if code == 3:
        return reason or "Pip needs a little setup first. Open Settings → Your AI."
    detail = f" ({reason[:160]})" if reason else ""
    return (
        f"Pip hit a snag preparing “{title}”{detail}. Open the book and choose Prepare more to try again; "
        "the full story is in its pipeline.log."
    )


@dataclass
class Scanned:
    id: str
    folder: Path
    book: dict | None
    book_mtime: float | None
    own: dict
    progress: dict
    progress_mtime: float | None
    meta: dict
    log_mtime: float
    elsewhere: bool
    activity: dict | None
    activity_mtime: float | None


@dataclass
class State:
    runs: dict = field(default_factory=dict)  # id -> runner.Run
    ran_with: dict = field(default_factory=dict)  # id -> prep.Window
    by_person: set = field(default_factory=set)
    stopping: set = field(default_factory=set)
    adding: set = field(default_factory=set)
    removing: set = field(default_factory=set)
    problems: dict = field(default_factory=dict)  # id -> {code, detail, card}
    last_lines: dict = field(default_factory=dict)  # id -> words for the card


class Library:
    def __init__(
        self, notify: Callable[..., None] | None = None, emit: Callable[[str, object], None] | None = None
    ):
        self.notify = notify or (lambda **_: None)
        self.emit = emit or (lambda *_: None)
        self.settings = JsonFile(paths.home() / "settings.json")
        self.records = JsonFile(paths.home() / "runs.json")
        self.lock = threading.RLock()
        self.state = State()
        self.scanned: dict[str, Scanned] = {}
        self.usage: dict | None = None
        self.usage_checked = 0.0
        self.message: str | None = None
        self.app_active = False
        self._shelf_json: str = ""
        self._stop = threading.Event()
        self._refresh_lock = threading.Lock()

    # The background loop.

    def start(self) -> None:
        threading.Thread(target=self._loop, name="library", daemon=True).start()

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        self.refresh()
        self.refresh_usage(force=True)
        self.resume_unfinished()
        ticks = 0
        while not self._stop.wait(4):
            with contextlib.suppress(Exception):  # one bad look never stops the shelf
                self.refresh()
            ticks += 1
            if ticks % 75 == 0:  # every ~5 minutes: usage, retries whose limit lifted, maybe a gentle nudge
                threading.Thread(target=self.refresh_usage, daemon=True).start()
                self.resume_unfinished()
                self.nudge_tick()

    def refresh_usage(self, force: bool = False) -> dict | None:
        """NotebookLM's allowance, read at most every five minutes (or now, when `force`: the account page, a
        sign-in). Never while a book is being prepared, forced or not: every NotebookLM command rotates
        Google's session cookie, and one alongside a run can leave the saved session signed out."""
        if not force and time.time() - self.usage_checked < 300:
            return self.usage
        if any(e["preparing"] for e in self.entries()):
            return self.usage
        self.usage_checked = time.time()
        _, lines = runner.once(["--usage"], timeout=60)
        for line in lines:
            if parsed := prep.parse_usage(line):
                self.usage = parsed
        with contextlib.suppress(Exception):  # the window shows it next time it asks
            self.emit("shelf", self.shelf())
        return self.usage

    # Looking at the shelf.

    def _scan_one(self, folder: Path, old: Scanned | None) -> Scanned:
        def mtime(path: Path) -> float | None:
            try:
                return path.stat().st_mtime
            except OSError:
                return None

        book_mtime = mtime(folder / "book.json") or mtime(folder / "book-data.js")
        book = old.book if old and old.book_mtime == book_mtime else books.load(folder)
        progress_mtime = mtime(folder / "progress.json")
        if old and old.progress_mtime == progress_mtime:
            own, merged = old.own, old.progress
        else:
            own, merged = progress.load_merged(folder)
        meta = JsonFile(folder / "meta.json").read()
        activity_mtime = mtime(folder / "activity.json")
        if old and old.activity_mtime == activity_mtime:
            activity = old.activity
        else:
            try:
                activity = prep.read_activity((folder / "activity.json").read_bytes())
            except OSError:
                activity = None
        return Scanned(
            id=folder.name,
            folder=folder,
            book=book,
            book_mtime=book_mtime,
            own=own,
            progress=merged,
            progress_mtime=progress_mtime,
            meta=meta,
            log_mtime=(mtime(folder / "pipeline.log") or 0) * 1000,
            elsewhere=portable.is_locked(folder / ".running"),
            activity=activity,
            activity_mtime=activity_mtime,
        )

    def refresh(self) -> None:
        with self._refresh_lock:
            root = paths.books()
            found = {}
            for folder in sorted(root.iterdir()) if root.exists() else []:
                if folder.is_dir() and pipeline_run.is_valid_id(folder.name):
                    with self.lock:
                        if folder.name in self.state.removing:
                            continue
                    found[folder.name] = self._scan_one(folder, self.scanned.get(folder.name))
            with self.lock:
                self.scanned = found
            self.announce()
            shelf = self.shelf()
            text = json.dumps(shelf, sort_keys=True, default=str)
            if text != self._shelf_json:
                self._shelf_json = text
                self.emit("shelf", shelf)

    def running_here(self, book_id: str) -> bool:
        with self.lock:
            return book_id in self.state.runs or book_id in self.state.adding

    def entries(self) -> list[dict]:
        """Every book with what the shelf needs, newest first."""
        with self.lock:
            scanned = [s for s in self.scanned.values() if s.id not in self.state.removing]
            adding = set(self.state.adding)
        out = []
        for item in scanned:
            running = self.running_here(item.id)
            preparing = running or item.elsewhere
            with self.lock:
                line = self.state.last_lines.get(item.id, "") if running else ""
                problem = None if preparing else self.state.problems.get(item.id)
            if item.elsewhere and not running:
                last = runner.LogFollower.last_progress(item.folder / "pipeline.log")
                line = (
                    describe(pipeline_run.parse_line(last)) if last else None
                ) or "Pip is getting started…"
            out.append(
                {
                    "id": item.id,
                    "folder": item.folder,
                    "book": item.book,
                    "progress": item.progress,
                    "preparing": preparing,
                    "lastLine": line,
                    "activity": item.activity if preparing else None,
                    "problem": problem,
                    "addedAt": item.meta.get("addedAt", 0),
                }
            )
        for book_id in adding:  # still being copied in
            if book_id not in self.scanned:
                out.append(
                    {
                        "id": book_id,
                        "folder": paths.books() / book_id,
                        "book": None,
                        "progress": progress.empty(),
                        "preparing": True,
                        "lastLine": "Pip is getting started…",
                        "activity": None,
                        "problem": None,
                        "addedAt": now_ms(),
                    }
                )
        return sorted(out, key=lambda e: -float(e["addedAt"] or 0))

    def card(self, entry: dict) -> dict:
        """One book as the shelf draws it."""
        b, p = entry["book"], entry["progress"]
        chapters = b["chapters"] if b else []
        dots = study.dots(chapters, p)
        closed = dots.count("closed")
        ready = sum(1 for c in chapters if c["status"].get("study") == "done")
        title = b["title"] if b else entry["id"].replace("-", " ")
        if not chapters:
            counts = ""
        elif ready == 0:
            counts = f"{len(chapters)} chapters · the first one is on its way"
        elif closed == 0:
            counts = f"{ready} of {len(chapters)} chapters ready"
        else:
            counts = f"{closed} of {len(chapters)} loops closed · {ready} ready"
        if not b:
            made = ""
        elif b["dryRun"]:
            made = "A practice run"
        elif b["engine"] == "local":
            made = f"Made with {b['model'] or 'your AI'}"
        elif b["engine"] == "auto" and b["model"]:
            made = f"Made with NotebookLM and {b['model']}"
        else:
            made = "Made with NotebookLM"
        working = None
        if entry["activity"] and entry["activity"]["items"]:
            item = entry["activity"]["items"][0]
            measured = prep.item_progress(item, now_ms())
            working = {
                "n": item["n"],
                "item": ITEM_NAMES.get(item["item"], item["item"]),
                "step": measured["step"],
                "detail": measured["detail"],
                "fraction": measured["fraction"],
                "percent": prep.percent_text(measured),
                "by": measured["by"],
            }
        return {
            "id": entry["id"],
            "title": title,
            "cover": study.cover_index(title, 5),
            "dots": dots,
            "counts": counts,
            "madeWith": made,
            "preparing": entry["preparing"],
            "line": entry["lastLine"] or ("Pip is getting started…" if entry["preparing"] else ""),
            "working": working,
            "problem": entry["problem"],
            "chapters": len(chapters),
        }

    def shelf(self) -> dict:
        entries = self.entries()
        now = now_ms()
        summary = study.shelf_summary(entries, now)
        resume = summary["resume"]
        if resume:
            entry = next(e for e in entries if e["id"] == resume["id"])
            chapter = next(c for c in entry["book"]["chapters"] if c["n"] == resume["n"])
            audio = books.file_in(entry["folder"], chapter.get("audio"))
            resume = {
                **resume,
                "book": entry["book"]["title"],
                "stageLabel": loop.LABELS[resume["stage"]],
                "cover": study.cover_index(entry["book"]["title"], 5),
                "audio": chapter["audio"] if audio and audio.exists() else None,
            }
        log = study.combined_log([e["progress"]["log"] for e in entries])
        today = now
        return {
            "books": [self.card(e) for e in entries],
            "summary": {
                **summary,
                "resume": resume,
                "preparing": len(summary["preparing"]),
                "weekText": study.format_duration(summary["weekSeconds"]),
            },
            "year": {
                "grid": study.year_grid(log, today),
                "stats": study.year_stats(log, today),
                "totalText": study.format_duration(study.year_stats(log, today)["total"]),
            },
            "message": self.take_message(),
        }

    def take_message(self) -> str | None:
        with self.lock:
            message, self.message = self.message, None
        return message

    def say(self, message: str) -> None:
        with self.lock:
            self.message = message
        self.emit("message", message)

    # "Chapter N is ready" (ChapterReady): once ever per chapter, for the chapter you can study next.

    def nudge_settings(self) -> dict:
        return nudges.parse_settings(self.settings.get("nudgeSettings"))

    def announce(self) -> None:
        settings = self.nudge_settings()
        with self.lock:
            scanned = list(self.scanned.values())
        ids = {s.id for s in scanned}
        watching = {k: v for k, v in (self.settings.get("chapterReadyWatching") or {}).items() if k in ids}
        announced = {k: v for k, v in (self.settings.get("chapterReadyAnnounced") or {}).items() if k in ids}
        saved = (json.dumps(watching, sort_keys=True), json.dumps(announced, sort_keys=True))
        now = dt.datetime.now()
        quiet = nudges.is_quiet(settings, now.timestamp() * 1000, now.hour)
        for item in scanned:
            if not item.book:
                continue
            chapter, keep = prep.ready_step(
                item.book,
                item.progress,
                set(watching.get(item.id, [])),
                set(announced.get(item.id, [])),
                quiet,
            )
            if keep:
                watching[item.id] = sorted(keep)
            else:
                watching.pop(item.id, None)
            if chapter is None:
                continue
            announced[item.id] = sorted(set(announced.get(item.id, [])) | {chapter["n"]})
            if nudges.allows(settings, "chapterReady"):
                title, body = prep.ready_message(chapter, item.book["title"])
                self.notify(title=title, body=body, book_id=item.id)
        if json.dumps(watching, sort_keys=True) != saved[0]:
            self.settings.set("chapterReadyWatching", watching)
        if json.dumps(announced, sort_keys=True) != saved[1]:
            self.settings.set("chapterReadyAnnounced", announced)

    # Pip's nudges (Nudger).

    def nudge_tick(self) -> None:
        books_now = [(e["book"], e["progress"]) for e in self.entries() if e["book"]]
        now = dt.datetime.now()
        today = now.strftime("%Y-%m-%d")
        history = nudges.parse_history(self.settings.get("nudgeHistory"))
        chosen = nudges.decide(
            books_now,
            self.nudge_settings(),
            history,
            now.timestamp() * 1000,
            now.hour,
            today,
            self.app_active,
        )
        if chosen:
            self.send_nudge(chosen, day=today)

    def send_nudge(self, chosen: dict, day: str | None = None, test: bool = False) -> None:
        now = now_ms()
        if not test:
            history = nudges.parse_history(self.settings.get("nudgeHistory"))
            nudges.sent(history, chosen, now, day or study.day_key(now))
            self.settings.set("nudgeHistory", history)
        self.notify(title=chosen["title"], body=chosen["body"], book_id="", nudge=chosen, test=test)

    def engaged(self) -> None:
        history = nudges.parse_history(self.settings.get("nudgeHistory"))
        nudges.engaged(history, now_ms())
        self.settings.set("nudgeHistory", history)

    def pause_until_tomorrow(self) -> None:
        settings = self.nudge_settings()
        settings["pausedUntil"] = nudges.pause_until_tomorrow(dt.datetime.now(), settings["quietEnd"])
        self.settings.set("nudgeSettings", settings)

    # Adding and preparing books.

    @property
    def prepare_everything(self) -> bool:
        return bool(self.settings.get("prepareEverything", False))

    def window_for(self, item: Scanned) -> prep.Window:
        media = (item.meta.get("options") or {}).get("media", "1-2")
        return prep.window(item.book, item.progress, prep.wants_everything(self.prepare_everything, media))

    def add(self, file: str, practice: bool = False, title: str | None = None, wait: bool = False) -> bool:
        """A dropped or picked book: copied into the library off the main thread, then Pip starts preparing
        it."""
        source = Path(file)
        if source.suffix.lower() not in (".pdf", ".epub"):
            self.say("Pip can read PDF and EPUB books.")
            return False
        title = pipeline_run.book_title(title, str(source))
        with self.lock:
            taken = set(self.scanned) | self.state.adding | self.state.removing
            taken |= {p.name for p in paths.books().iterdir()}
            book_id = pipeline_run.unique(pipeline_run.slug(title), taken)
            self.state.adding.add(book_id)
        folder = paths.books() / book_id
        folder.mkdir(parents=True, exist_ok=True)
        copy = folder / f"source{source.suffix.lower()}"

        def work() -> None:
            try:
                shutil.copyfile(source, copy)
            except OSError:
                with self.lock:
                    self.state.adding.discard(book_id)
                shutil.rmtree(folder, ignore_errors=True)
                self.say(
                    f"Pip couldn't copy “{source.name}”. Check that the file isn't still downloading, "
                    "then try again."
                )
                self.refresh()
                return
            meta = {
                "path": str(copy),
                "originalPath": str(source),
                "addedAt": now_ms(),
                "title": title,
                "options": {"media": "1-2", "dryRun": practice},
            }
            JsonFile(folder / "meta.json").write(meta)
            with self.lock:
                self.state.adding.discard(book_id)
            win = prep.window(None, progress.empty(), self.prepare_everything)
            self.prepare(book_id, copy, win, dry_run=practice, title=title, by_person=True)
            self.refresh()

        self.emit("shelf", self.shelf())
        if wait:
            work()
        else:
            threading.Thread(target=work, daemon=True).start()
        return True

    def add_sample(self) -> bool:
        return self.add(str(paths.sample_book()), practice=True, title="Sample book")

    def resume_unfinished(self) -> None:
        with self.lock:
            ids = list(self.scanned)
        for book_id in ids:
            self.resume(book_id)

    def resume(self, book_id: str) -> None:
        now = now_ms()
        with self.lock:
            item = self.scanned.get(book_id)
            busy = (
                book_id in self.state.runs or book_id in self.state.adding or book_id in self.state.removing
            )
        if not item or busy or item.elsewhere or not item.book:
            return
        win = self.window_for(item)
        record = (self.records.read() or {}).get(book_id)
        source = item.meta.get("path")
        if not (
            prep.has_auto_work(item.book, win, self.usage, item.log_mtime, now)
            and prep.may_start(record, float(self.settings.get("settingsChangedAt", 0)), now)
            and source
            and Path(source).exists()
        ):
            return
        retry = any("waiting_quota" in c["status"].values() for c in item.book["chapters"])
        self.prepare(
            book_id,
            Path(source),
            win,
            dry_run=bool((item.meta.get("options") or {}).get("dryRun")),
            retry=retry,
        )

    def study_moved(self, book_id: str) -> None:
        """A study step was finished: the chapters prepared just ahead may move."""

        def later() -> None:
            self.refresh()
            self.resume(book_id)

        threading.Thread(target=later, daemon=True).start()

    def _startable(self, book_id: str) -> bool:
        with self.lock:
            item = self.scanned.get(book_id)
            if book_id in self.state.runs or (item and item.elsewhere):
                self.say("Pip is already working on this book. Give it a moment to finish, then try again.")
                return False
        return item is not None

    def prepare_more(self, book_id: str) -> None:
        """Podcasts and videos for every chapter, and another try for anything that failed. Remembered."""
        if not self._startable(book_id):
            return
        item = self.scanned[book_id]
        meta = JsonFile(item.folder / "meta.json")
        data = meta.read()
        data.setdefault("options", {})["media"] = "all"
        meta.write(data)
        self.prepare(book_id, Path(data.get("path", "")), prep.EVERYTHING, retry=True, by_person=True)
        self.refresh()

    def make_with_my_ai(self, book_id: str) -> None:
        """Make a book's waiting items now with your own AI instead of waiting for NotebookLM."""
        if not self._startable(book_id):
            return
        item = self.scanned[book_id]
        win = self.window_for(item)
        self.prepare(
            book_id,
            Path(item.meta.get("path", "")),
            win,
            dry_run=bool((item.meta.get("options") or {}).get("dryRun")),
            retry=True,
            engine="local",
            by_person=True,
        )
        self.refresh()

    def prepare(
        self,
        book_id: str,
        source: Path,
        win: prep.Window,
        dry_run: bool = False,
        retry: bool = False,
        engine: str | None = None,
        title: str | None = None,
        by_person: bool = False,
    ) -> None:
        out = paths.books() / book_id
        if title is None:
            meta = JsonFile(out / "meta.json").read()
            title = pipeline_run.saved_title(meta.get("title"), meta.get("originalPath"))
        args = pipeline_run.arguments(
            str(source),
            str(out),
            win.chapters_spec,
            win.media_spec,
            dry_run=dry_run,
            retry=retry,
            engine=engine,
            title=title,
        )
        run = runner.Run()
        with self.lock:
            self.state.runs[book_id] = run
            self.state.ran_with[book_id] = win
            self.state.problems.pop(book_id, None)
            self.state.last_lines[book_id] = ""
            if by_person:
                self.state.by_person.add(book_id)
            else:
                self.state.by_person.discard(book_id)
        try:
            run.start(
                args,
                out / "pipeline.log",
                lambda line: self._line(book_id, line),
                lambda code, tail: self._finished(book_id, code, tail),
            )
        except OSError as error:
            with self.lock:
                self.state.runs.pop(book_id, None)
                self.state.ran_with.pop(book_id, None)
                self.state.by_person.discard(book_id)
            self.say(f"Pip couldn't start preparing: {error}")

    def _line(self, book_id: str, raw: str) -> None:
        parsed = pipeline_run.parse_line(raw)
        words = describe(parsed)
        if words:
            with self.lock:
                self.state.last_lines[book_id] = words
        if parsed["kind"] == "made":
            threading.Thread(target=self.refresh, daemon=True).start()
        else:
            self.emit("line", {"id": book_id, "line": words})

    def _finished(self, book_id: str, code: int, tail: list[str]) -> None:
        with self.lock:
            win = self.state.ran_with.pop(book_id, None)
            by_person = book_id in self.state.by_person
            self.state.by_person.discard(book_id)
            self.state.runs.pop(book_id, None)
            stopped = book_id in self.state.stopping
            self.state.stopping.discard(book_id)
        if stopped:
            self.refresh()
            return
        if not any("already being prepared" in t for t in tail):
            records = self.records.read()
            records[book_id] = prep.record_after(records.get(book_id), code, now_ms())
            self.records.write(records)
        item = self.scanned.get(book_id)
        title = item.book["title"] if item and item.book else "Your book"
        said = outcome(title, code, tail)
        if code != 0 and said:
            if by_person:
                self.say(said)
            else:
                with self.lock:
                    self.state.problems[book_id] = {
                        "code": code,
                        "detail": said,
                        "card": prep.run_problem(code, tail),
                    }
        self.refresh()
        item = self.scanned.get(book_id)
        if win and item and item.book:
            current = self.window_for(item)
            if prep.start_again(win, current, code, current.has_work(item.book)):
                self.resume(book_id)

    # Removing books.

    def remove_book(self, book_id: str) -> None:
        """Off the shelf now; the folder goes to the Recycle Bin once any run preparing it has stopped."""
        if not pipeline_run.is_valid_id(book_id):
            return
        folder = paths.books() / book_id
        with self.lock:
            self.state.removing.add(book_id)
            self.scanned.pop(book_id, None)
            run = self.state.runs.get(book_id)
            if run:
                self.state.stopping.add(book_id)
        if run:
            run.stop()
        else:
            stop_run_elsewhere(folder)

        def later() -> None:
            deadline = time.time() + 5
            while portable.is_locked(folder / ".running") and time.time() < deadline:
                time.sleep(0.1)
            to_recycle_bin(folder)
            with self.lock:
                self.state.removing.discard(book_id)
            self.refresh()

        self.emit("shelf", self.shelf())
        threading.Thread(target=later, daemon=True).start()

    def remove_all_books(self) -> None:
        for entry in self.entries():
            self.remove_book(entry["id"])
        self.records.remove()

    def library_size(self) -> int:
        total = 0
        for path in paths.books().rglob("*"):
            with contextlib.suppress(OSError):
                if path.is_file():
                    total += path.stat().st_size
        return total

    def settings_changed(self) -> None:
        """Exit 2 and 3 wait for settings to change; they just did."""
        self.settings.set("settingsChangedAt", now_ms())
        threading.Thread(target=self.resume_unfinished, daemon=True).start()


def stop_run_elsewhere(folder: Path) -> None:
    """A run this app didn't start (the command line, or before a relaunch): its pid is in `.running`, trusted
    only while that run holds the lock."""
    lock = folder / ".running"
    if not portable.is_locked(lock):
        return
    try:
        pid = int(lock.read_text().strip())
    except (OSError, ValueError):
        return
    if pid <= 1:
        return
    import subprocess

    if portable.WINDOWS:
        subprocess.run(
            ["taskkill", "/T", "/F", "/PID", str(pid)], capture_output=True, **portable.no_window()
        )
    else:
        import os
        import signal

        with contextlib.suppress(OSError):
            os.kill(pid, signal.SIGTERM)


def to_recycle_bin(folder: Path) -> None:
    """To the Recycle Bin when there is one (so a slip can be undone), otherwise removed."""
    if not folder.exists():
        return
    try:
        from send2trash import send2trash

        send2trash(str(folder))
    except Exception:
        shutil.rmtree(folder, ignore_errors=True)
