"""Ticket lifecycle transitions + id allocation (SAIPEN discipline adapted).

Rules (from SAIPEN CORE 1.2, SAIPENVIEW protocol, simplified for one human):

- new ticket -> TODO (I2)
- start: TODO -> DOING; refused while any `needs:` dependency is not DONE
- done: DOING -> DONE
- block: TODO/DOING -> BLOCKED; `blocked-by` reason REQUIRED
- unblock: BLOCKED -> TODO; the decision/evidence REQUIRED
- reopen: DONE -> TODO
- a ticket never sits under two headings; `blocked-by` exists iff BLOCKED
"""

from __future__ import annotations

import datetime
import re
from datetime import UTC

from .board import render_board
from .model import BLOCKED, DOING, DONE, TODO, Board, Ticket

_ID_SCAN = re.compile(r"[ST]-(\d+)")


def now_stamp() -> str:
    return datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def today() -> str:
    return datetime.datetime.now(UTC).date().isoformat()


def next_ticket_id(board: Board, log_text: str = "") -> str:
    """The next free S-id: max over the whole board AND the log (SAIPEN rule:
    the board alone cannot prove an id was never issued — pruned DONE tickets
    and sealed log segments keep the history)."""
    highest = 0
    for text in (render_board(board), log_text):
        for m in _ID_SCAN.finditer(text):
            try:
                highest = max(highest, int(m.group(1)))
            except ValueError:
                continue
    return f"S-{highest + 1}"


class TransitionRefused(Exception):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def _stamp(ticket: Ticket) -> None:
    ticket.set_field("updated", now_stamp())


def create_ticket(
    board: Board,
    title: str,
    *,
    tid: str | None = None,
    log_text: str = "",
    fields=None,
    status=TODO,
) -> Ticket:
    title = (title or "").strip()
    if not title:
        raise TransitionRefused("title is empty")
    tid = tid or next_ticket_id(board, log_text)
    if board.get(tid) is not None:
        raise TransitionRefused(f"{tid} already on the board")
    ticket = Ticket(tid, title)
    if fields:
        for k, v in fields:
            if v:
                ticket.set_field(k, v)
    ticket.set_field("created", today())
    _stamp(ticket)
    board.add(ticket, status=status)
    return ticket


def transition(board: Board, ticket_id: str, target: str, reason: str | None = None) -> Ticket:
    """Validate and apply one lifecycle edge. Raises TransitionRefused."""
    ticket = board.get(ticket_id)
    if ticket is None:
        raise TransitionRefused(f"{ticket_id} not on the board")
    src = ticket.status

    if target == DOING:
        if src != TODO:
            raise TransitionRefused(f"start accepts only TODO, {ticket_id} is under {src}")
        unmet = [n for n in ticket.needs if board.get(n) is None or board.get(n).status != DONE]
        if unmet:
            raise TransitionRefused(
                f"{ticket_id} has unmet needs: {', '.join(unmet)}; finish those tickets first"
            )
    elif target == DONE:
        if src != DOING:
            raise TransitionRefused(f"done accepts only DOING, {ticket_id} is under {src}")
    elif target == BLOCKED:
        if src not in (TODO, DOING):
            raise TransitionRefused(f"block accepts only TODO/DOING, {ticket_id} is under {src}")
        if not (reason or "").strip():
            raise TransitionRefused("block requires a reason: the facts/dead ends that justify it")
        ticket.set_field("blocked-by", reason.strip())
    elif target == TODO:
        if src == BLOCKED:
            if not (reason or "").strip():
                raise TransitionRefused(
                    "unblock requires the decision/evidence that lifts the block"
                )
            ticket.remove_field("blocked-by")
        elif src == DONE:
            pass  # reopen, no reason required
        else:
            raise TransitionRefused(f"cannot move {ticket_id} from {src} to TODO")
    else:
        raise TransitionRefused(f"unknown target status {target!r}")

    board.move(ticket_id, target)
    _stamp(ticket)
    return ticket
