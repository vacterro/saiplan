"""Per-plan notes + backlinks (extras, spec 7). Planner-relevant only:
plain markdown files beside the data, `[[S-001]]` links between tickets and
notes. No vault, no graph, no plugin system.

Note filenames keep Unicode (multilingual) but strip only path-unsafe
characters; writes are atomic. A human's note is data, not scratch.
"""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path

from ..core.persistence import atomic_write

LINK_RE = re.compile(r"\[\[([ST]-\d+)\]\]")
_PATH_UNSAFE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_DEVICES = {
    "con",
    "prn",
    "aux",
    "nul",
    *(f"com{i}" for i in range(1, 10)),
    *(f"lpt{i}" for i in range(1, 10)),
}


def safe_note_name(name: str) -> str:
    """Unicode-preserving filesystem-safe note stem."""
    name = unicodedata.normalize("NFC", name or "").strip()
    name = _PATH_UNSAFE.sub("_", name)
    name = re.sub(r"\s+", " ", name).strip(" ._")
    name = name or "note"
    if name.split(".")[0].lower() in _DEVICES:
        name = f"note-{name}"
    return name


def note_path(plan, name: str) -> Path:
    """Resolve a note name to a file under the plan's notes/ dir."""
    return plan.notes_dir / f"{safe_note_name(name)}.md"


def list_notes(plan) -> list[Path]:
    return sorted(plan.notes_dir.glob("*.md"))


def read_note(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return ""


def write_note(plan, name: str, text: str) -> Path:
    plan.ensure_dirs()
    path = note_path(plan, name)
    atomic_write(path, text)
    return path


def ticket_links(text: str) -> list[str]:
    return LINK_RE.findall(text)


def backlinks(plan, ticket_id: str) -> list[Path]:
    """Notes referencing the ticket (via [[S-001]])."""
    return [p for p in list_notes(plan) if ticket_id in ticket_links(read_note(p))]


def note_search(plan, query: str) -> list[Path]:
    q = query.lower()
    return [p for p in list_notes(plan) if q in read_note(p).lower()]
