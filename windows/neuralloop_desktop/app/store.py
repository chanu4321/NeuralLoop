"""Small JSON files the app keeps for itself (settings.json, runs.json), written atomically and read
leniently."""

import contextlib
import json
import threading
from pathlib import Path
from typing import Any

from neuralloop_books import portable


class JsonFile:
    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.Lock()

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

    def set(self, key: str, value: Any) -> None:
        with self._lock:
            data = self.read()
        data[key] = value
        self.write(data)

    def remove(self) -> None:
        with contextlib.suppress(OSError):
            self.path.unlink()
