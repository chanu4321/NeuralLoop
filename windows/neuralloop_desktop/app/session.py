"""One open book (BookSession.swift): its data, this device's progress, the study clock, and the steps that
complete
themselves from what the person really did (spec 09). Every change saves progress.json at once (small,
atomic)."""

import json
import threading
import time
from pathlib import Path

from ..core import book as books
from ..core import coverage, loop, progress, study
from . import runner


def now_ms() -> float:
    return time.time() * 1000


class Session:
    def __init__(self, folder: Path, on_step: "callable | None" = None):
        self.folder = folder
        self.id = folder.name
        self.on_step = on_step or (lambda *_: None)
        self.lock = threading.RLock()
        self.book = books.load(folder) or books.parse({"title": "Your book"})
        own, merged = progress.load_merged(folder)
        self.progress = merged
        self.own_log = dict(own["log"])
        self.lengths: dict[int, dict[str, float]] = {}
        self._book_mtime = self._mtime("book.json")
        self._last_tracking_save = 0.0
        self._tracking_unsaved = False

    def _mtime(self, name: str) -> float | None:
        try:
            return (self.folder / name).stat().st_mtime
        except OSError:
            return None

    def reload_book(self) -> bool:
        """The pipeline rewrote book.json (a new item): read it again. True when it changed."""
        mtime = self._mtime("book.json")
        if mtime == self._book_mtime:
            return False
        fresh = books.load(self.folder)
        if fresh:
            with self.lock:
                self.book, self._book_mtime = fresh, mtime
        return True

    def chapter(self, n: int) -> dict | None:
        return next((c for c in self.book["chapters"] if c["n"] == n), None)

    def save(self) -> None:
        with self.lock:
            progress.save(self.progress, self.folder, own_log=self.own_log)

    # Steps.

    def complete(self, n: int, stage: str) -> bool:
        with self.lock:
            closed = loop.complete(self.progress, n, stage, now_ms())
        self.save()
        self.on_step(self.id)
        return closed

    def earn(self, n: int, stage: str) -> dict | None:
        """A step ticked off because the person really did it: only in an open chapter, never undoing
        anything."""
        with self.lock:
            changed = loop.complete_if_open(self.progress, self.book["chapters"], n, stage, now_ms())
        if changed is None:
            return None
        self.save()
        self.on_step(self.id)
        return {"n": n, "stage": stage, "closed": changed, "label": loop.LABELS[stage]}

    def remember(self, n: int, stage: str) -> None:
        with self.lock:
            if self.progress["last"] == {"n": n, "stage": stage}:
                return
            progress.set_last(self.progress, n, stage, now_ms())
        self.save()

    # Quiz.

    def quiz(self, n: int) -> dict:
        return loop.quiz_state(self.progress["quiz"].get(str(n)))

    def set_quiz(self, n: int, i: int, results: list[bool]) -> dict | None:
        with self.lock:
            progress.set_quiz(
                self.progress, str(n), {"i": max(0, int(i)), "results": [bool(r) for r in results]}, now_ms()
            )
        self.save()
        chapter = self.chapter(n)
        if chapter and loop.quiz_finished(self.progress, chapter):
            return self.earn(n, "recall")
        return None

    # Recall in your own words.

    def check_recall(self, n: int, index: int, answer: str) -> dict:
        """The recall model from Settings checks each key point; word matching when it can't."""
        chapter = self.chapter(n)
        if not chapter or not chapter["recall"]:
            return {"covered": [], "feedback": "", "by": ""}
        prompt = chapter["recall"][min(max(0, index), len(chapter["recall"]) - 1)]
        request = json.dumps(
            {"question": prompt["prompt"], "keyPoints": prompt["keyPoints"], "answer": answer}
        )
        _, lines = runner.once(["--grade-recall"], stdin=request, timeout=240)
        result = None
        for line in reversed(lines):
            try:
                parsed = json.loads(line)
            except ValueError:
                continue
            if isinstance(parsed, dict):
                result = parsed
                break
        marks = result.get("covered") if result else None
        if isinstance(marks, list) and len(marks) == len(prompt["keyPoints"]):
            covered = [m is True for m in marks]
            feedback = result.get("feedback") or study.recall_feedback(prompt["keyPoints"], covered)
            by = result.get("by") or ""
        else:
            covered = study.word_match(prompt["keyPoints"], answer)
            feedback, by = study.recall_feedback(prompt["keyPoints"], covered), "word match"
        earned = self.earn(n, "recall") if loop.is_real_answer(answer) else None
        return {"covered": covered, "feedback": feedback, "by": by, "earned": earned}

    # Remaking the mind map from memory.

    def remake(self, n: int) -> dict:
        saved = self.progress["remake"].get(str(n))
        saved = saved if isinstance(saved, dict) else {}
        guess = saved.get("guess") if isinstance(saved.get("guess"), str) else ""
        best = saved.get("best") if isinstance(saved.get("best"), (int, float)) else 0
        return {"guess": guess, "best": int(best)}

    def set_remake_draft(self, n: int, guess: str) -> None:
        current = self.remake(n)
        if guess == current["guess"]:
            return
        with self.lock:
            progress.set_remake(self.progress, str(n), {"guess": guess, "best": current["best"]}, now_ms())
        self.save()

    def check_remake(self, n: int, guess: str) -> dict:
        chapter = self.chapter(n)
        if not chapter or not chapter["mindmap"]:
            return {"rows": [], "percent": 0}
        result = study.compare(guess, chapter["mindmap"])
        best = max(self.remake(n)["best"], result["percent"])
        with self.lock:
            progress.set_remake(self.progress, str(n), {"guess": guess, "best": best}, now_ms())
        self.save()
        return {**result, "best": best, "earned": self.earn(n, "map")}

    def place_on_map(self, placed: dict, seen: list[int]) -> None:
        now = now_ms()
        with self.lock:
            for node, point in placed.items():
                if isinstance(point, list) and len(point) == 2:
                    progress.set_map_pos(self.progress, node, point, now)
            merged_seen = sorted(set(self.progress["mapSeen"]) | {int(x) for x in seen})
            if not placed and merged_seen == self.progress["mapSeen"]:
                return
            self.progress["mapSeen"] = merged_seen
            self.progress["updatedAt"] = max(self.progress["updatedAt"], now)
        self.save()

    # Flashcards.

    def review(self, card_id: str, rating: str) -> dict | None:
        score = loop.RATINGS.get(rating)
        if not score:
            return None
        with self.lock:
            self.progress["cards"][card_id] = loop.grade(self.progress["cards"].get(card_id), score, now_ms())
            self.progress["updatedAt"] = now_ms()
        self.save()
        n = int(card_id.split(":")[0]) if card_id.split(":")[0].isdigit() else None
        chapter = self.chapter(n) if n is not None else None
        if chapter and loop.cards_all_seen(self.progress, chapter):
            return self.earn(n, "space")
        return None

    def due(self, n: int | None = None) -> list[dict]:
        """Cards to review now: one chapter's, or every open chapter's."""
        chapters = [c for c in self.book["chapters"] if n is None or c["n"] == n]
        return loop.due_cards(chapters if n is not None else self.book["chapters"], self.progress, now_ms())

    # Listening and reading (spec 09).

    def record_play(
        self, n: int, kind: str, start: float, end: float, rate: float, wall: float, length: float
    ) -> dict | None:
        if kind not in ("audio", "video"):
            return None
        if length and length > 0:
            self.lengths.setdefault(n, {})[kind] = float(length)
        with self.lock:
            counted = loop.record_play(self.progress, n, kind, start, end, rate, wall)
        if not counted:
            return None
        known = self.lengths.get(n, {})
        if coverage.listening_done(
            self.progress["watch"].get(str(n)), known.get("audio"), known.get("video")
        ):
            return self.earn(n, "prime")
        self._save_tracking()
        return None

    def credit_reading(
        self, n: int, visible: list[int], seconds: float, needs: list[float], earning: bool
    ) -> dict | None:
        with self.lock:
            credited = loop.credit_reading(self.progress, n, visible, seconds, len(needs), earning)
        if not credited:
            return None
        if coverage.reading_progress(self.progress["reading"].get(str(n)), needs)["done"]:
            return self.earn(n, "read")
        self._save_tracking()
        return None

    def _save_tracking(self) -> None:
        """Listening and reading are written at most every 15 seconds (they change every second)."""
        self._tracking_unsaved = True
        if time.time() - self._last_tracking_save >= 15:
            self.flush()

    def flush(self) -> None:
        if self._tracking_unsaved:
            self._tracking_unsaved = False
            self._last_tracking_save = time.time()
            self.save()

    # The study clock: 15-second ticks while the book is in front.

    def tick(self, seconds: float) -> None:
        seconds = max(0.0, min(15.0, float(seconds)))
        if seconds <= 0:
            return
        now = now_ms()
        with self.lock:
            study.log_study(self.progress, now, seconds)
            key = study.day_key(now)
            self.own_log[key] = self.own_log.get(key, 0.0) + seconds
        self.save()
