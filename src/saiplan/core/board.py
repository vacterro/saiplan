"""Strict BOARD.md parser/writer (SAIPEN grammar + SAIPLAN human fields).

Grammar (from SAIPEN CORE 1.2, audited in docs/REFERENCE_AUDIT.md):

    ## DOING / ## TODO / ## DONE / ## BLOCKED     (each exactly once)
    - [ ] S-### Title | key: value | key2: v2

- checkbox must agree with its section: `[ ]` TODO/BLOCKED, `[/]` DOING,
  `[x]` DONE.
- field separator is ` | `; a literal `|` in any value is escaped `\\|` and a
  literal backslash `\\\\` (backslash first, then pipe — SAIPEN rule).
- duplicate single-valued field is malformed (never last-write-wins).
- a ticket appears under exactly one heading.

Diagnostics are split into two channels:

- **errors** are structural/fatal: the input contains bytes that cannot be
  represented losslessly (a malformed line, a malformed field fragment, a
  duplicate ID, a duplicate single-valued field, a missing/duplicate required
  heading, a ticket under an unknown heading, a checkbox/section
  contradiction). A board with any error MUST NOT be silently canonicalized
  and saved (I3/I4/I5) — it is preserved instead.
- **warnings** are losslessly representable notes (an unknown but well-formed
  `key: value` field). Such a field is kept byte-for-byte on re-render, so a
  board with only warnings IS writable.
"""

from __future__ import annotations

import re

from .model import (
    BLOCKED,
    DOING,
    DONE,
    KNOWN_FIELDS,
    SECTION_ORDER,
    STATUS_CHECKBOX,
    TODO,
    Board,
    Ticket,
)

REQUIRED_HEADINGS = tuple(f"## {s}" for s in SECTION_ORDER)
TICKET_RE = re.compile(r"^- \[([ x/])\] (\S+)\s+(.*)$")
FIELD_RE = re.compile(r"^([a-z][a-z0-9-]*):\s*(.*)$")

_PIPE_SENTINEL = "\x00"


def escape_value(value: str) -> str:
    """Reversibly escape a field/title payload (backslash first, pipe second)."""
    return value.replace("\\", "\\\\").replace("|", "\\|")


def unescape_value(value: str) -> str:
    return value.replace("\\\\", "\\").replace(_PIPE_SENTINEL, "|")


def _escape_line_body(title: str, fields: list[tuple[str, str]]) -> str:
    """Build the `Title | k: v` body with escapes applied, then strip pipes."""
    parts = [escape_value(title)]
    for key, value in fields:
        parts.append(f"{key}: {escape_value(value)}" if value else f"{key}:")
    return " | ".join(parts)


def render_ticket(ticket: Ticket) -> str:
    body = _escape_line_body(ticket.title, ticket.fields)
    return f"- [{STATUS_CHECKBOX[ticket.status]}] {ticket.ticket_id} {body}"


def _parse_ticket_line(line: str):
    """Strict single-line parse -> (Ticket, checkbox, errors, warnings).

    errors are structural (cannot be represented losslessly): the caller must
    treat the whole BOARD as non-writable.
    warnings are informational (unknown well-formed field) — such fields are
    preserved on re-render, so they never block saving.
    """
    masked = line.replace("\\|", _PIPE_SENTINEL)
    m = TICKET_RE.match(masked)
    if not m:
        return None, "", ["line does not match `- [ ] S-### title` shape"], []
    checkbox, tid, rest = m.groups()
    if not re.match(r"^(S|T)-\d+$", tid):
        return None, checkbox, [f"ticket id {tid!r} is not of the form S-###"], []
    parts = [p.strip() for p in rest.split(" | ")]
    title = unescape_value(parts[0]) if parts else ""
    fields: list[tuple[str, str]] = []
    seen = set()
    warnings = []
    for part in parts[1:]:
        fm = FIELD_RE.match(part)
        if not fm:
            # a fragment that is not `key: value` cannot be re-rendered
            # losslessly -> structural, makes the board non-writable
            return None, checkbox, [f"malformed field fragment {part!r}"], []
        key, value = fm.groups()
        if key in seen:
            return None, checkbox, [f"duplicate single-valued field {key!r}"], []
        seen.add(key)
        if key not in KNOWN_FIELDS:
            warnings.append(f"unknown field {key!r} preserved")
        fields.append((key, unescape_value(value)))
    return Ticket(tid, title, fields=fields, raw=line), checkbox, [], warnings


def parse_board_detailed(text: str) -> tuple[Board, list[str], list[str]]:
    """(board, errors, warnings). See module docstring for the split.

    A board with a non-empty `errors` list is NOT writable: it contains bytes
    that a canonical re-render would destroy. Malformed lines never crash —
    the parser records the problem and keeps what it can for display.
    """
    board = Board()
    current: str | None = None
    errors: list[str] = []
    warnings: list[str] = []
    heading_seen: dict[str, int] = {}
    seen_ids: set[str] = set()
    for line_no, line in enumerate(text.splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        if line.startswith("## "):
            heading = line
            current = heading
            heading_seen[heading] = heading_seen.get(heading, 0) + 1
            continue
        if current is None:
            errors.append(f"BOARD.md:{line_no}: content before any section heading")
            continue
        ticket, checkbox, errs, warns = _parse_ticket_line(line)
        if ticket is None:
            errors.extend(f"BOARD.md:{line_no}: {e}" for e in errs)
            continue
        warnings.extend(f"BOARD.md:{line_no}: {w}" for w in warns)
        if ticket.ticket_id in seen_ids:
            errors.append(
                f"BOARD.md:{line_no}: duplicate ticket id "
                f"{ticket.ticket_id}; keeping the first occurrence"
            )
            continue
        section = current[3:].strip()
        if section not in SECTION_ORDER:
            errors.append(
                f"BOARD.md:{line_no}: ticket {ticket.ticket_id} under unknown heading {current!r}"
            )
            continue
        expected = {" ": (TODO, BLOCKED), "/": DOING, "x": DONE}
        if section not in expected.get(checkbox, ()):
            errors.append(
                f"BOARD.md:{line_no}: checkbox/section disagreement for {ticket.ticket_id}"
            )
        ticket.status = section
        board.sections[section].append(ticket)
        seen_ids.add(ticket.ticket_id)
    for h in REQUIRED_HEADINGS:
        n = heading_seen.get(h, 0)
        if n != 1:
            errors.append(f"required heading {h} appears {n} time(s)")
    return board, errors, warnings


def parse_board(text: str) -> tuple[Board, list[str]]:
    """Backward-compatible: (Board, errors). Warnings are dropped here."""
    board, errors, _warnings = parse_board_detailed(text)
    return board, errors


def board_text_is_strictly_valid(text: str) -> bool:
    """True only for a canonical board that parses with zero structural errors."""
    if not text or not text.strip():
        return False
    _board, errors, _warnings = parse_board_detailed(text)
    return not errors


def render_board(board: Board) -> str:
    """Canonical BOARD text: four headings always present, one trailing NL."""
    lines = []
    for s in SECTION_ORDER:
        lines.append(f"## {s}")
        for ticket in board.sections[s]:
            lines.append(render_ticket(ticket))
    return "\n".join(lines) + "\n"
