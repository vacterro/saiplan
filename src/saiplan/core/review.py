"""Plan Review — advisory checks (spec 5). Warnings advise; only structurally
corrupt state blocks. Every check returns (severity, message) tuples."""

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


def vague_title(title: str) -> bool:
    words = [w for w in title.split() if w.isalnum() or any(c.isalnum() for c in w)]
    return len(words) < 4


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
        if t.status in (TODO, DOING) and vague_title(t.title):
            findings.append(
                (WARN, t.ticket_id, ("vague ticket — state WHAT, the outcome, or what comes next"))
            )
        for need in t.needs:
            if need not in ids:
                findings.append(
                    (WARN, t.ticket_id, f"needs {need} which does not exist on the board")
                )
                continue
            if by_id[need].status in (TODO, DOING, BLOCKED):
                findings.append((WARN, t.ticket_id, f"depends on {need} which is not DONE"))
        if t.status in (TODO, DOING) and not t.get("done-when") and not t.get("verify"):
            findings.append((INFO, t.ticket_id, ("no completion criterion (done-when) set")))

    # cycles: check every ticket once
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
        else:
            ok = any(
                x in t.get("blocked-by").lower()
                for x in (" because", "waiting", "need", "due", ":")
            )
            if not ok:
                findings.append((INFO, t.ticket_id, "blocked-by reads like a label, not a fact"))

    # DONE ticket depended on by an unresolved ticket is a contradiction hint
    for t in tickets:
        if t.status != DONE:
            continue
        dependents = [o.ticket_id for o in tickets if t.ticket_id in o.needs and o.status != DONE]
        if dependents:
            findings.append(
                (INFO, t.ticket_id, f"DONE but still needed by: {', '.join(dependents)}")
            )

    return findings
