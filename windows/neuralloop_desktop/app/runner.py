"""Runs the book pipeline (PipelineRunner.swift).

Installed, the app runs itself as the pipeline (`NeuralLoop.exe --pipeline …`, the same Python and packages
inside
it). From the repo it runs `pipeline/nl_book.py` with the Python that runs the app. Output goes straight to
the
book's pipeline.log, so a run keeps going if the window closes or the app quits; while the app is open, a
follower
reads new lines as they come.
"""

import contextlib
import datetime as dt
import os
import subprocess
import sys
import threading
import time
from collections import deque
from collections.abc import Callable
from pathlib import Path

from neuralloop_books import portable

from ..core import pipeline_run
from . import keys, paths


def command() -> list[str]:
    if paths.frozen():
        return [sys.executable, "--pipeline"]
    return [sys.executable, str(paths.bundle() / "pipeline" / "nl_book.py")]


def environment() -> dict[str, str]:
    """The person's ai.json and saved keys; keys and AI addresses the app was started with are left behind."""
    config = paths.ai_config()
    env = pipeline_run.environment(
        dict(os.environ), keys.all_keys(), str(config) if config.exists() else None
    )
    env["NEURALLOOP_HOME"] = str(paths.home())
    env.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(paths.home() / "browsers"))
    ollama = find_ollama()
    if ollama:
        env["NEURALLOOP_OLLAMA"] = ollama
    return env


def find_ollama() -> str | None:
    """Ollama for Windows installs per user and puts itself on PATH; look in its usual place too."""
    import shutil

    found = shutil.which("ollama")
    if found:
        return found
    local = os.environ.get("LOCALAPPDATA")
    if local:
        candidate = Path(local) / "Programs" / "Ollama" / "ollama.exe"
        if candidate.exists():
            return str(candidate)
    return None


class LogFollower:
    """Reads lines appended to a log from `offset` on, and keeps the last few for "what happened"."""

    def __init__(self, path: Path, offset: int, on_line: Callable[[str], None]):
        self.path, self.offset, self.on_line = path, offset, on_line
        self.tail: deque[str] = deque(maxlen=12)
        self._stop = threading.Event()
        self._partial = b""
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=2)
        self._read()  # whatever came in last

    def _run(self) -> None:
        while not self._stop.wait(0.25):
            self._read()

    def _read(self) -> None:
        try:
            with open(self.path, "rb") as handle:
                handle.seek(self.offset)
                data = handle.read()
        except OSError:
            return
        if not data:
            return
        self.offset += len(data)
        *lines, self._partial = (self._partial + data).split(b"\n")
        for raw in lines:
            line = raw.decode("utf-8", errors="replace").rstrip("\r")
            if line.strip():
                self.tail.append(line.strip())
                with contextlib.suppress(Exception):  # a broken listener never stops the follower
                    self.on_line(line)

    @staticmethod
    def last_progress(path: Path) -> str | None:
        """The last progress line in a log (for a run started elsewhere)."""
        try:
            with open(path, "rb") as handle:
                handle.seek(0, os.SEEK_END)
                size = handle.tell()
                handle.seek(max(0, size - 8192))
                text = handle.read().decode("utf-8", errors="replace")
        except OSError:
            return None
        for line in reversed(text.splitlines()):
            if line.strip() and not line.startswith("—"):
                return line
        return None


class Run:
    """One pipeline run for one book."""

    def __init__(self):
        self.process: subprocess.Popen | None = None
        self.follower: LogFollower | None = None

    def start(
        self,
        arguments: list[str],
        log: Path,
        on_line: Callable[[str], None],
        on_exit: Callable[[int, list[str]], None],
    ) -> None:
        log.parent.mkdir(parents=True, exist_ok=True)
        with open(log, "ab") as out:
            out.write(f"\n— {dt.datetime.now():%Y-%m-%d %H:%M:%S} —\n".encode())
            offset = out.tell()
        output = open(log, "ab")  # noqa: SIM115 - the child keeps writing to it; closed here once it has its own
        self.process = subprocess.Popen(
            [*command(), *arguments],
            stdout=output,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            env=environment(),
            cwd=str(paths.home()),
            **portable.own_group(),
        )
        output.close()  # the child has its own handle now
        self.follower = LogFollower(log, offset, on_line)
        self.follower.start()

        def wait() -> None:
            code = self.process.wait()
            self.follower.stop()
            on_exit(code, list(self.follower.tail))

        threading.Thread(target=wait, daemon=True).start()

    def stop(self) -> None:
        if self.process and self.process.poll() is None:
            portable.end_tree(self.process, wait=3)


def once(
    arguments: list[str],
    stdin: str | None = None,
    timeout: float = 120,
    cancel: threading.Event | None = None,
) -> tuple[int, list[str]]:
    """A quick pipeline command (sign in, account, usage, check AI, grade recall, setup): (exit code,
    lines)."""
    try:
        process = subprocess.Popen(
            [*command(), *arguments],
            stdin=subprocess.PIPE if stdin is not None else subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            env=environment(),
            cwd=str(paths.home()),
            **portable.own_group(),
        )
    except OSError as error:
        return 3, [f"NeuralLoop's engine couldn't start: {error}"]
    lines: list[str] = []

    def read() -> None:
        for raw in process.stdout:
            lines.append(raw.decode("utf-8", errors="replace").rstrip("\r\n"))

    reader = threading.Thread(target=read, daemon=True)
    reader.start()
    if stdin is not None:
        with contextlib.suppress(OSError):
            process.stdin.write(stdin.encode())
            process.stdin.close()
    deadline = time.monotonic() + timeout
    while process.poll() is None:
        if time.monotonic() > deadline or (cancel is not None and cancel.is_set()):
            portable.end_tree(process, wait=3)
            reader.join(timeout=2)
            return (130 if cancel is not None and cancel.is_set() else 124), lines
        time.sleep(0.1)
    reader.join(timeout=2)
    return process.returncode, lines


def stream(
    arguments: list[str], on_line: Callable[[str], None], cancel: threading.Event | None = None
) -> int:
    """A longer command whose lines matter as they come (sign-in, setup)."""
    try:
        process = subprocess.Popen(
            [*command(), *arguments],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            env=environment(),
            cwd=str(paths.home()),
            **portable.own_group(),
        )
    except OSError as error:
        on_line(f"NeuralLoop's engine couldn't start: {error}")
        return 3
    if cancel is not None:

        def watch() -> None:
            while process.poll() is None:
                if cancel.wait(0.2):
                    portable.end_tree(process, wait=3)
                    return

        threading.Thread(target=watch, daemon=True).start()
    for raw in process.stdout:
        line = raw.decode("utf-8", errors="replace").rstrip("\r\n")
        if line.strip():
            with contextlib.suppress(Exception):
                on_line(line)
    code = process.wait()
    return 130 if cancel is not None and cancel.is_set() else code
