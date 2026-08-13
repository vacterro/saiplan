"""Per-plan notes + backlinks (extras, spec 7). Planner-relevant only:
plain markdown files beside the data, `[[S-001]]` links between tickets and
notes. No vault, no graph, no plugin system.
"""

from __future__ import annotations

import re
from pathlib import Path

LINK_RE = re.compile(r"\[\[([ST]-\d+)\]\]")


def note_path(plan, name: str) -> Path:
    """Resolve a note name to a file under the plan's notes/ dir."""
    safe = re.sub(r"[^A-Za-z0-9_.\- ]+", "", name).strip() or "note"
    return plan.notes_dir / f"{safe}.md"


def list_notes(plan) -> list[Path]:
    return sorted(plan.notes_dir.glob("*.md"))


def read_note(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def write_note(plan, name: str, text: str) -> Path:
    plan.ensure_dirs()
    path = note_path(plan, name)
    path.write_text(text, encoding="utf-8")
    return path


def ticket_links(text: str) -> list[str]:
    return LINK_RE.findall(text)


def backlinks(plan, ticket_id: str) -> list[Path]:
    """Notes referencing the ticket (via [[S-001]])."""
    return [p for p in list_notes(plan) if ticket_id in read_note(p)]


def note_search(plan, query: str) -> list[Path]:
    q = query.lower()
    return [p for p in list_notes(plan) if q in read_note(p).lower()]
