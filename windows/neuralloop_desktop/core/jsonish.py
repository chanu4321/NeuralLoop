"""Small helpers for lenient JSON: numbers that may be bools or strings, and stable bytes on disk."""

import json
import math
from typing import Any


def number(value: Any) -> float | None:
    """A JSON number as float (bools are 1/0: the study site wrote `closedShown: true`); else None."""
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    if isinstance(value, (int, float)) and math.isfinite(value):
        return float(value)
    return None


def integer(value: Any) -> int | None:
    n = number(value) if not isinstance(value, bool) else None
    return int(n) if n is not None and n == int(n) else None


def rounded(x: float) -> float:
    """Swift's `.rounded()`: half away from zero (Python's `round` goes to even)."""
    return float(math.floor(x + 0.5)) if x >= 0 else -float(math.floor(-x + 0.5))


def tenth(x: float) -> float:
    """To a tenth, as the Mac app writes play spans and reading seconds."""
    return rounded(x * 10) / 10


def text(value: Any, default: str = "") -> str:
    return value if isinstance(value, str) else default


def _tidy(value: Any) -> Any:
    """Whole floats as ints (what Swift's encoder writes), recursively."""
    if isinstance(value, float) and math.isfinite(value) and value == int(value) and abs(value) < 1e15:
        return int(value)
    if isinstance(value, dict):
        return {k: _tidy(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_tidy(v) for v in value]
    return value


def dumps(value: Any) -> bytes:
    """Sorted keys, compact, whole numbers without ".0": the same data always makes the same bytes."""
    return json.dumps(_tidy(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
