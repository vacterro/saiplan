"""Compact statistics (extras). No dashboards of meaningless charts — a few
honest numbers from the plain files (spec 6/14).

Everything derives from canonical files; there is no hidden index to go stale.
"""

from __future__ import annotations

import datetime
import json
import math
from datetime import UTC

from ..core.logbook import read_log


def board_counts(controller) -> dict[str, int]:
    return controller.board.counts()


def status_totals(plan) -> dict[str, int]:
    """Ticket counts by status read straight off BOARD.md."""
    from ..core.board import parse_board_detailed, validate_board_semantics

    try:
        text = plan.board_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return {}
    board, errors, _warnings = parse_board_detailed(text)
    if errors or validate_board_semantics(board):
        return {}
    return board.counts()


def activity_counts(plan) -> dict[str, int]:
    """Semantic LOG events, grouped by type."""
    out = {}
    for entry in read_log(plan.log_path):
        event = entry["event"]
        out[event] = out.get(event, 0) + 1
    return out


def _closed_sessions(plan) -> list[dict]:
    try:
        lines = plan.timelog_path.read_bytes().splitlines()
    except OSError:
        return []
    sessions: dict[str, dict] = {}
    for raw in lines:
        if not raw.strip():
            continue
        try:
            rec = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            continue
        if not isinstance(rec, dict) or rec.get("kind") != "ticket" or not rec.get("ended_at"):
            continue
        session_id = rec.get("session_id")
        duration = rec.get("duration_s")
        try:
            duration_value = float(duration)
        except (OverflowError, TypeError, ValueError):
            continue
        if (
            not isinstance(session_id, str)
            or isinstance(duration, bool)
            or not isinstance(duration, (int, float))
            or not math.isfinite(duration_value)
            or duration_value < 0
        ):
            continue
        sessions.setdefault(session_id, rec)
    return list(sessions.values())


def time_spent(plan, ticket_id: str) -> float:
    return sum(
        float(rec["duration_s"])
        for rec in _closed_sessions(plan)
        if rec.get("ticket_id") == ticket_id
    )


def total_time(plan) -> float:
    return sum(float(rec["duration_s"]) for rec in _closed_sessions(plan))


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
