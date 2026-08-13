"""Ticket lifecycle: transitions, id allocation, dependency gates."""

import pytest
from conftest import build_board

from saiplan.core.lifecycle import TransitionRefused, create_ticket, next_ticket_id, transition
from saiplan.core.model import BLOCKED, DOING, DONE, TODO, Board


def test_new_ticket_defaults_to_todo():
    board = Board()
    t = create_ticket(board, "Buy SSD")
    assert t.status == TODO
    assert board.counts()["TODO"] == 1


def test_id_is_monotonic_and_never_reused():
    board = Board()
    t1 = create_ticket(board, "One")
    t2 = create_ticket(board, "Two")
    assert t1.ticket_id == "S-1"
    assert t2.ticket_id == "S-2"
    board.remove(t2.ticket_id)
    # the log records that S-2 was issued -> id is never reused
    assert next_ticket_id(board, "TICKET_CREATED [S-2]") == "S-3"


def test_id_accounts_for_log_history():
    board = build_board("DONE S-007 Old")
    assert next_ticket_id(board, "log mentions S-042 and S-5") == "S-43"


def test_empty_title_refused():
    with pytest.raises(TransitionRefused):
        create_ticket(Board(), "   ")


def test_duplicate_id_refused():
    board = build_board("TODO S-001 A")
    with pytest.raises(TransitionRefused):
        create_ticket(board, "B", tid="S-001")


def test_full_flow_todo_doing_done():
    board = Board()
    t = create_ticket(board, "Install SSD")
    transition(board, t.ticket_id, DOING)
    assert t.status == DOING
    transition(board, t.ticket_id, DONE)
    assert t.status == DONE


def test_done_requires_doing():
    board = Board()
    t = create_ticket(board, "Task")
    with pytest.raises(TransitionRefused):
        transition(board, t.ticket_id, DONE)


def test_start_refused_with_unmet_needs():
    board = Board()
    dep = create_ticket(board, "Research models")
    t = create_ticket(board, "Order SSD")
    t.set_field("needs", dep.ticket_id)
    with pytest.raises(TransitionRefused) as ei:
        transition(board, t.ticket_id, DOING)
    assert "needs" in str(ei.value)


def test_start_allowed_after_dependency_done():
    board = Board()
    dep = create_ticket(board, "Research models")
    t = create_ticket(board, "Order SSD")
    t.set_field("needs", dep.ticket_id)
    transition(board, dep.ticket_id, DOING)
    transition(board, dep.ticket_id, DONE)
    transition(board, t.ticket_id, DOING)  # must not raise


def test_block_requires_reason():
    board = Board()
    t = create_ticket(board, "Task")
    with pytest.raises(TransitionRefused):
        transition(board, t.ticket_id, BLOCKED)
    transition(board, t.ticket_id, BLOCKED, reason="waiting for parts")
    assert t.get("blocked-by") == "waiting for parts"
    assert t.status == BLOCKED


def test_unblock_requires_decision_and_removes_blocked_by():
    board = Board()
    t = create_ticket(board, "Task")
    transition(board, t.ticket_id, BLOCKED, reason="waiting")
    with pytest.raises(TransitionRefused):
        transition(board, t.ticket_id, TODO)
    transition(board, t.ticket_id, TODO, reason="parts arrived")
    assert t.status == TODO
    assert not t.get("blocked-by")


def test_reopen_done_to_todo():
    board = Board()
    t = create_ticket(board, "Task")
    transition(board, t.ticket_id, DOING)
    transition(board, t.ticket_id, DONE)
    transition(board, t.ticket_id, TODO)
    assert t.status == TODO


def test_blocked_cannot_start_directly():
    board = Board()
    t = create_ticket(board, "Task")
    transition(board, t.ticket_id, BLOCKED, reason="x")
    with pytest.raises(TransitionRefused):
        transition(board, t.ticket_id, DOING)


def test_ticket_never_under_two_headings():
    board = Board()
    t = create_ticket(board, "Task")
    transition(board, t.ticket_id, DOING)
    assert len([x for x in board.all_tickets() if x.ticket_id == t.ticket_id]) == 1
    assert board.sections[DOING].count(t) == 1
    assert board.sections[TODO].count(t) == 0


def test_unknown_target_refused():
    board = Board()
    t = create_ticket(board, "Task")
    with pytest.raises(TransitionRefused):
        transition(board, t.ticket_id, "WIP")


def test_transition_unknown_ticket_refused():
    with pytest.raises(TransitionRefused):
        transition(Board(), "S-999", DOING)


def test_created_and_updated_stamped():
    board = Board()
    t = create_ticket(board, "Task")
    assert t.get("created")
    assert t.get("updated")
