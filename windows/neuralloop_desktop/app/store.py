"""Small JSON files the app keeps for itself (settings.json, runs.json), written atomically and read
leniently. Every change is one read, change and write under one lock (`update`), so two threads never lose
each other's changes (a "chapter ready" announced twice, a silly nudge played again)."""

import contextlib
import json
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any, TypeVar

from neuralloop_books import portable

T = TypeVar("T")


class JsonFile:
    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.RLock()

    def read(self) -> dict:
        try:
            data = json.loads(self.path.read_bytes())
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def write(self, data: dict) -> None:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_name(self.path.name + ".tmp")
            tmp.write_text(json.dumps(data, sort_keys=True, indent=1, ensure_ascii=False), encoding="utf-8")
            portable.replace(tmp, self.path)

    def get(self, key: str, default: Any = None) -> Any:
        return self.read().get(key, default)

    def update(self, change: Callable[[dict], T]) -> T:
        """Read, `change` the data in place, and write it back, all under the file's lock."""
        with self._lock:
            data = self.read()
            result = change(data)
            self.write(data)
            return result

    def set(self, key: str, value: Any) -> None:
        self.update(lambda data: data.__setitem__(key, value))

    def remove(self) -> None:
        with contextlib.suppress(OSError):
            self.path.unlink()
