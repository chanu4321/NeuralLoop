"""CI: turn pytest's JUnit XML into GitHub annotations, so failures show on the run's page (and in its API)
without opening the log. `python scripts/ci_annotate.py results.xml [more.xml…]`; at most 40 are written."""

import sys
import xml.etree.ElementTree as ET
from pathlib import Path

LIMIT = 40


def escape(text: str) -> str:
    return text.replace("%", "%25").replace("\r", "").replace("\n", "%0A")


def escape_title(text: str) -> str:
    return escape(text).replace(":", "%3A").replace(",", "%2C")


def failures(path: Path) -> list[tuple[str, str]]:
    found = []
    for case in ET.parse(path).iter("testcase"):
        for problem in [*case.iter("failure"), *case.iter("error")]:
            name = f"{case.get('classname', '')}::{case.get('name', '')}"
            detail = (problem.get("message") or "") + "\n" + (problem.text or "")
            found.append((name, detail.strip()[-1500:]))
    return found


def missing(path: Path) -> list[tuple[str, str]]:
    """No results at all: pytest died. Its output (results.txt, written by `tee`) says why."""
    output = path.with_suffix(".txt")
    tail = ""
    if output.exists():
        tail = "\n".join(output.read_text(encoding="utf-8", errors="replace").splitlines()[-30:])
    return [(f"{path.name} wasn't written", tail or "pytest stopped before writing its results")]


def main(paths: list[str]) -> int:
    found = [f for p in paths for f in (failures(Path(p)) if Path(p).exists() else missing(Path(p)))]
    for name, detail in found[:LIMIT]:
        print(f"::error title={escape_title(name)}::{escape(detail)}")
    if len(found) > LIMIT:
        print(f"::error::{len(found) - LIMIT} more failures; see the log.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
