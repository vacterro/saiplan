"""Compact statistics (extras). No dashboards of meaningless charts — a few
honest numbers from the plain files (spec 6/14).

Everything derives from canonical files; there is no hidden index to go stale.
"""

from __future__ import annotations

import datetime
from datetime import UTC

from ..core.logbook import read_log


def board_counts(controller) -> dict[str, int]:
    return controller.board.counts()


def status_totals(plan) -> dict[str, int]:
    """Ticket counts by status read straight off BOARD.md."""
    from ..core.board import parse_board

    try:
        text = plan.board_path.read_text(encoding="utf-8")
    except OSError:
        return {}
    board, _errors = parse_board(text)
    return board.counts()


def activity_counts(plan) -> dict[str, int]:
    """Semantic LOG events, grouped by type."""
    out = {}
    for entry in read_log(plan.log_path):
        event = entry["event"]
        out[event] = out.get(event, 0) + 1
    return out


def time_spent(plan, ticket_id: str) -> float:
    """Total seconds recorded in TIMELOG.jsonl for a ticket."""
    total = 0.0
    try:
        lines = plan.timelog_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return 0.0
    import json

    for line in lines:
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if rec.get("kind") == "ticket" and rec.get("ticket_id") == ticket_id:
            total += float(rec.get("duration_s", 0))
    return total


def total_time(plan) -> float:
    try:
        lines = plan.timelog_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return 0.0
    import json

    total = 0.0
    for line in lines:
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if rec.get("kind") == "ticket":
            total += float(rec.get("duration_s", 0))
    return total


def completed_today(plan) -> int:
    today = datetime.datetime.now(UTC).date().isoformat()
    return sum(
        1
        for e in read_log(plan.log_path)
        if e["event"] == "TICKET_DONE" and e["ts"].startswith(today)
    )


def completed_last_days(plan, days: int = 7) -> int:
    cutoff = (datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=days)).strftime(
        "%Y-%m-%d"
    )
    return sum(
        1 for e in read_log(plan.log_path) if e["event"] == "TICKET_DONE" and e["ts"] >= cutoff
    )
