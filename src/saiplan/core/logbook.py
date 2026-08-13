"""Semantic plan history (LOG.md). Spec 18: meaningful events only, concise,
chronological. App debug/crash logs live separately under logs/."""

from __future__ import annotations

import datetime
from pathlib import Path

EVENTS = frozenset(
    {
        "PLAN_CREATED",
        "TICKET_CREATED",
        "TICKET_STARTED",
        "TICKET_BLOCKED",
        "TICKET_UNBLOCKED",
        "TICKET_DONE",
        "TICKET_REOPENED",
        "TICKET_EDITED",
        "TICKET_DELETED",
        "TICKET_RESTORED",
        "PLAN_REVIEWED",
        "RECOVERY_USED",
        "CONFLICT_DETECTED",
        "BATCH_CREATED",
    }
)


def _now() -> str:
    return datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def append_event(
    path: Path, event: str, ticket: str | None = None, detail: str | None = None
) -> None:
    """Append one semantic event line. Non-atomic on purpose (LOG is history,
    not authority); a torn tail line is skipped on read."""
    if event not in EVENTS:
        raise ValueError(f"unknown semantic event {event!r}")
    parts = [f"- {_now()} {event}"]
    if ticket:
        parts.append(f"[{ticket}]")
    if detail:
        parts.append(f"-- {detail}")
    line = " ".join(parts) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(line)


def read_log(path: Path) -> list[dict]:
    """Chronological events. A torn last line (crash mid-append) is skipped."""
    out = []
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return out
    for line in raw.splitlines():
        line = line.strip()
        if not line.startswith("- "):
            continue
        body = line[2:]
        ts, _, rest = body.partition(" ")
        event, _, rest = rest.partition(" ")
        if event not in EVENTS:
            continue
        ticket = ""
        if rest.startswith("[") and "]" in rest:
            ticket, _, rest = rest[1:].partition("]")
            ticket = ticket.strip()
            rest = rest.strip().lstrip("-").strip()
        out.append({"ts": ts, "event": event, "ticket": ticket or None, "detail": rest or None})
    return out


def ticket_ids_in_log(text: str) -> list[str]:
    """Every S-###/T-### referenced anywhere in a log (for id allocation)."""
    import re

    return re.findall(r"[ST]-\d+", text)
