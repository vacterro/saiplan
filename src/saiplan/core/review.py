"""Plan Review — advisory checks (spec 5). Warnings advise; only structurally
corrupt state blocks. Low-noise by design: waiting on a legitimate open
prerequisite is NORMAL planning and never warned about.

WARN (actionable / contradictory):
- empty plan
- duplicate title
- dangling dependency (`needs:` a ticket that is not on the board)
- dependency cycle
- DOING ticket whose prerequisites are not DONE (working before its own input)
- DONE ticket whose own prerequisites are not DONE (finished before its input)
- BLOCKED without a blocked-by reason
- multiple DOING under single-focus mode

INFO (optional improvement only):
- no completion criterion (done-when) set
- short title (actionability heuristic only, never a blocker)
"""

from __future__ import annotations

from .model import BLOCKED, DOING, DONE, TODO, Board

WARN, INFO = "warn", "info"


def _cycle_members(board: Board, start_id: str) -> list[str] | None:
    """Walk the needs graph from `start_id`; return the cycle containing it
    if one exists."""
    seen = set()
    path = []

    def walk(tid):
        if tid in path:
            i = path.index(tid)
            return path[i:] + [tid]
        if tid in seen:
            return None
        seen.add(tid)
        ticket = board.get(tid)
        if ticket is None:
            return None
        path.append(tid)
        for need in ticket.needs:
            cyc = walk(need)
            if cyc:
                return cyc
        path.pop()
        return None

    return walk(start_id)


def review_board(board: Board, *, single_focus: bool = True) -> list[tuple[str, str, str]]:
    """-> [(severity, ticket_id or '', message)]"""
    findings: list[tuple[str, str, str]] = []
    tickets = board.all_tickets()
    ids = {t.ticket_id for t in tickets}
    by_id = {t.ticket_id: t for t in tickets}

    if not tickets:
        findings.append((WARN, "", "empty plan — nothing to do yet"))

    titles = {}
    for t in tickets:
        low = " ".join(t.title.lower().split())
        if low in titles:
            findings.append((WARN, t.ticket_id, f"duplicate title: also {titles[low]}"))
        else:
            titles[low] = t.ticket_id

    for t in tickets:
        if t.status in (TODO, DOING):
            if len([w for w in t.title.split() if any(c.isalnum() for c in w)]) < 4:
                findings.append(
                    (INFO, t.ticket_id, "short title — consider an action/outcome phrasing")
                )
            if not t.get("done-when") and not t.get("verify"):
                findings.append((INFO, t.ticket_id, ("no completion criterion (done-when) set")))
        for need in t.needs:
            if need not in ids:
                findings.append(
                    (WARN, t.ticket_id, f"needs {need} which does not exist on the board")
                )
                continue
            need_ticket = by_id[need]
            if t.status == DOING and need_ticket.status != DONE:
                findings.append(
                    (WARN, t.ticket_id, f"is DOING but depends on {need} which is not DONE")
                )
            if t.status == DONE and need_ticket.status != DONE:
                findings.append(
                    (WARN, t.ticket_id, f"is DONE but its prerequisite {need} is not DONE")
                )  # cycles: check every ticket once
    checked = set()
    for t in tickets:
        if t.ticket_id in checked:
            continue
        cyc = _cycle_members(board, t.ticket_id)
        if cyc:
            checked.update(cyc)
            findings.append((WARN, t.ticket_id, f"circular dependency: {' -> '.join(cyc)}"))

    # multiple DOING under single-focus
    if single_focus and len(board.sections[DOING]) > 1:
        doing_ids = [t.ticket_id for t in board.sections[DOING]]
        findings.append((WARN, "", f"multiple tickets in DOING: {', '.join(doing_ids)}"))

    # blocked tickets must state why
    for t in board.sections[BLOCKED]:
        if not t.get("blocked-by"):
            findings.append((WARN, t.ticket_id, "BLOCKED without a blocked-by reason"))

    return findings
