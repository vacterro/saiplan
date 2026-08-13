"""Core model: statuses, ticket, board, lifecycle validation.

Qt-free. Everything a human planner needs to reason about a board lives here
so it is unit-testable headless.
"""

from __future__ import annotations

import re

# Statuses in canonical board order.
DOING, TODO, DONE, BLOCKED = "DOING", "TODO", "DONE", "BLOCKED"
SECTION_ORDER = (DOING, TODO, DONE, BLOCKED)

STATUS_CHECKBOX = {TODO: " ", DOING: "/", DONE: "x", BLOCKED: " "}

# Human/optional fields SAIPLAN owns. `blocked-by` is required exactly under
# BLOCKED (SAIPEN rule adapted); `created`/`updated` are stamped by the writer;
# `checklist` is a JSON list of {text, done} encoded into the single line.
KNOWN_FIELDS = frozenset(
    {
        "created",
        "updated",
        "priority",
        "due",
        "tags",
        "needs",
        "estimate",
        "done-when",
        "blocked-by",
        "details",
        "checklist",
    }
)

PRIORITY_ORDER = {"low": 0, "normal": 1, "high": 2, "urgent": 3}

ID_RE = re.compile(r"^(S|T)-(\d+)$")


class BoardError(ValueError):
    """A board that cannot be represented. Callers recover, never crash."""


class Ticket:
    """One ticket line. `fields` preserves the source order of `| key: v`
    parts so a parsed-and-written board round-trips byte-stably."""

    __slots__ = ("fields", "raw", "status", "ticket_id", "title")

    def __init__(self, ticket_id, title, status=TODO, fields=None, raw=None):
        self.ticket_id = ticket_id
        self.title = title
        self.status = status
        self.fields = list(fields) if fields else []
        self.raw = raw

    # -- field access -------------------------------------------------
    def get(self, key, default=""):
        for k, v in self.fields:
            if k == key:
                return v
        return default

    def set_field(self, key, value):
        for i, (k, _) in enumerate(self.fields):
            if k == key:
                self.fields[i] = (key, value)
                return
        self.fields.append((key, value))

    def remove_field(self, key):
        self.fields = [(k, v) for k, v in self.fields if k != key]

    def has_field(self, key):
        return any(k == key for k, _ in self.fields)

    # -- derived ------------------------------------------------------
    @property
    def needs(self) -> list[str]:
        """Dependency ticket ids from `needs:`. Malformed entries ignored."""
        raw = self.get("needs")
        return re.findall(r"[ST]-\d+", raw)

    @property
    def is_open(self):
        return self.status in (TODO, DOING, BLOCKED)

    @property
    def checkbox(self):
        return STATUS_CHECKBOX[self.status]

    def render(self) -> str:
        """Canonical line text. Escapes applied at encode time by the writer."""
        parts = [self.title]
        for key, value in self.fields:
            parts.append(f"{key}: {value}" if value else f"{key}:")
        body = " | ".join(parts)
        return f"- [{self.checkbox}] {self.ticket_id} {body}"


class Board:
    def __init__(self, sections=None):
        self.sections = (
            {s: list(sections.get(s) or []) for s in SECTION_ORDER}
            if sections
            else {s: [] for s in SECTION_ORDER}
        )

    def __iter__(self):
        for s in SECTION_ORDER:
            for t in self.sections[s]:
                yield s, t

    def all_tickets(self) -> list[Ticket]:
        return [t for _s, t in self]

    def counts(self) -> dict[str, int]:
        return {s: len(self.sections[s]) for s in SECTION_ORDER}

    def get(self, ticket_id) -> Ticket | None:
        for _s, t in self:
            if t.ticket_id == ticket_id:
                return t
        return None

    def move(self, ticket_id, status):
        """Move ticket to `status` and align its checkbox. Returns Ticket."""
        ticket = self.get(ticket_id)
        if ticket is None:
            raise BoardError(f"{ticket_id} not on the board")
        self.sections[ticket.status].remove(ticket)
        ticket.status = status
        self.sections[status].append(ticket)
        return ticket

    def add(self, ticket, status=TODO):
        """Insert a ticket into `status` (default TODO). Ticket keeps its id."""
        if self.get(ticket.ticket_id) is not None:
            raise BoardError(f"duplicate ticket id {ticket.ticket_id}")
        ticket.status = status
        self.sections[status].append(ticket)
        return ticket

    def remove(self, ticket_id) -> Ticket:
        ticket = self.get(ticket_id)
        if ticket is None:
            raise BoardError(f"{ticket_id} not on the board")
        self.sections[ticket.status].remove(ticket)
        return ticket

    def render(self) -> str:
        lines = []
        for s in SECTION_ORDER:
            lines.append(f"## {s}")
            for t in self.sections[s]:
                lines.append(t.render())
        return "\n".join(lines) + "\n"
