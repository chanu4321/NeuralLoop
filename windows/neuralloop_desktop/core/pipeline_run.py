"""Running the book pipeline: book ids, its command line, its environment, and reading its progress lines
(PipelineRun.swift, PipelineEnvironment.swift; the "Pipeline CLI" contract in CLAUDE.md)."""

import re
import uuid
from pathlib import PurePath


def parse_line(raw: str) -> dict:
    line = raw.strip()
    if line.startswith("Book: "):
        return {"kind": "finished"}
    if line.startswith("setup:"):
        return {"kind": "setup", "text": line[len("setup:") :].strip()}
    if m := re.match(r"^added chapter (\d+):", line):
        return {"kind": "added", "chapter": int(m[1])}
    if m := re.match(r"^✓ chapter (\d+) (\w+) \(", line):
        return {"kind": "made", "chapter": int(m[1]), "item": m[2]}
    if m := re.match(r"^↪ chapter (\d+) (\w+): .*making it with (.+)$", line):
        return {"kind": "fellBack", "chapter": int(m[1]), "item": m[2], "to": m[3]}
    if m := re.match(r"^… chapter (\d+) (\w+): .*limit reached", line):
        return {"kind": "waiting", "chapter": int(m[1]), "item": m[2]}
    if m := re.match(r"^✗ chapter (\d+) (\w+): (.*)$", line):
        return {"kind": "failed", "chapter": int(m[1]), "item": m[2], "reason": m[3]}
    return {"kind": "note", "text": line}


# Book ids are folder names the app creates: lowercase ASCII letters, digits, and dashes.


def is_valid_id(book_id: str) -> bool:
    return 0 < len(book_id) <= 80 and all((c.isascii() and c.isalnum()) or c == "-" for c in book_id)


def slug(text: str) -> str:
    out = ""
    for c in text.lower():
        if c.isascii() and c.isalnum():
            out += c
        elif out and not out.endswith("-"):
            out += "-"
    trimmed = out.strip("-")[:60]
    return trimmed or "book"


def unique(base: str, taken: set[str]) -> str:
    if base not in taken:
        return base
    n = 2
    while f"{base}-{n}" in taken:
        n += 1
    return f"{base}-{n}"


def arguments(
    book: str,
    out: str,
    chapters: str,
    media: str,
    dry_run: bool = False,
    retry: bool = False,
    engine: str | None = None,
    title: str | None = None,
) -> list[str]:
    """Engine, models and voices come from ai.json; keys only from the environment, never the command line."""
    args = [book, "--out", out, "--no-open", "--chapters", chapters, "--media", media]
    if dry_run:
        args.append("--dry-run")
    if retry:
        args.append("--retry")
    if engine:
        args += ["--engine", engine]
    if title:
        args.append(f"--title={title}")  # one argument, so a title like "-Draft" isn't read as a flag
    return args


INVISIBLE = {*range(0x202A, 0x202F), *range(0x2066, 0x206A), 0x200B, 0x200E, 0x200F, 0x2060, 0xFEFF}


def clean(text: str) -> str:
    """One line of plain words: invisible marks and control characters gone, runs of space collapsed."""
    kept = "".join(c for c in text if ord(c) not in INVISIBLE)
    parts = re.split(r"[\s\x00-\x1f\x7f]+", kept)
    return " ".join(p for p in parts if p)


def title_for_file(path: str) -> str | None:
    """ "Agents_guide.pdf" is "Agents guide"; None when nothing is left."""
    stem = PurePath(path.replace("\\", "/")).stem
    name = clean(stem.replace("_", " ").replace("-", " "))
    return name or None


def book_title(given: str | None, path: str) -> str:
    given = clean(given or "")
    if given:
        return given
    stem = PurePath(path.replace("\\", "/")).stem
    try:
        uuid.UUID(stem)
        return "Your book"
    except ValueError:
        pass
    return title_for_file(path) or "Your book"


def saved_title(title: str | None, original_path: str | None) -> str | None:
    saved = clean(title or "")
    if saved:
        return saved
    return book_title(None, original_path) if original_path else None


# The run's environment: never an inherited key, address, or ai.json; only the person's own saved keys.

KEY_NAMES = ["ANTHROPIC_API_KEY", "OPENAI_API_KEY", "OPENROUTER_API_KEY", "NEURALLOOP_API_KEY"]
NEVER_INHERITED = [
    *KEY_NAMES,
    "NEURALLOOP_BASE_URL",
    "NEURALLOOP_AI_CONFIG",
    "ANTHROPIC_BASE_URL",
    "ANTHROPIC_AUTH_TOKEN",
    "ANTHROPIC_API_URL",
    "ANTHROPIC_CUSTOM_HEADERS",
    "ANTHROPIC_PROFILE",
    "OPENAI_BASE_URL",
    "OPENAI_API_BASE",
    "OPENAI_ORG_ID",
    "OPENAI_ORGANIZATION",
    "OPENAI_PROJECT_ID",
    "OPENAI_CUSTOM_HEADERS",
    "OPENAI_ADMIN_KEY",
    "OPENROUTER_BASE_URL",
]
NEVER_INHERITED_PREFIXES = ("ANTHROPIC_", "OPENAI_", "OPENROUTER_", "AZURE_OPENAI_")


def environment(inherited: dict[str, str], keys: dict[str, str], ai_config: str | None) -> dict[str, str]:
    never = {n.upper() for n in NEVER_INHERITED}
    env = {
        k: v
        for k, v in inherited.items()
        if k.upper() not in never and not k.upper().startswith(NEVER_INHERITED_PREFIXES)
    }
    env["PYTHONUNBUFFERED"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"  # progress lines carry ✓ ↪ … ✗, whatever the Windows code page is
    if ai_config:
        env["NEURALLOOP_AI_CONFIG"] = ai_config
    for name in KEY_NAMES:
        if keys.get(name):
            env[name] = keys[name]
    return env
