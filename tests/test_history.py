"""Persisted undo/redo + trash (survive restart, spec 9/19)."""

from conftest import build_board

from saiplan.core.board import render_board
from saiplan.core.history import UNDO_CAP, History, Trash


def test_record_undo_redo_cycle(tmp_path):
    h = History(tmp_path)
    a = render_board(build_board("TODO S-001 A"))
    b = render_board(build_board("TODO S-002 B"))
    h.record("create", a, b)
    assert h.can_undo()
    assert not h.can_redo()
    assert h.undo(b) == a
    assert h.can_redo()
    assert not h.can_undo()
    assert h.redo(a) == b
    assert h.can_undo()  # record is back on the undo stack
    assert not h.can_redo()


def test_undo_survives_restart(tmp_path):
    h1 = History(tmp_path)
    a = render_board(build_board("TODO S-001 A"))
    b = render_board(build_board("TODO S-002 B"))
    h1.record("create", a, b)
    h2 = History(tmp_path)  # "restart"
    assert h2.undo(b) == a
    h3 = History(tmp_path)
    assert h3.redo(a) == b


def test_new_mutation_clears_redo(tmp_path):
    h = History(tmp_path)
    a = render_board(build_board("TODO S-001 A"))
    b = render_board(build_board("TODO S-002 B"))
    c = render_board(build_board("TODO S-003 C"))
    h.record("create", a, b)
    assert h.undo(b) == a
    h.record("create", a, c)  # new mutation invalidates redo
    assert not h.can_redo()


def test_undo_capped(tmp_path):
    h = History(tmp_path)
    for i in range(UNDO_CAP + 40):
        h.record(f"op{i}", f"prev{i}", f"after{i}")
    h2 = History(tmp_path)
    rec = h2._read_lines(h2.undo_path)
    assert len(rec) == UNDO_CAP
    assert h2.undo("after") is not None
    assert len(h2._read_lines(h2.undo_path)) == UNDO_CAP - 1


def test_corrupt_line_skipped(tmp_path):
    h = History(tmp_path)
    (tmp_path / "undo.jsonl").write_text("not json\n", encoding="utf-8")
    assert h.undo("x") is None
    assert not h.can_undo()


def test_trash_discard_and_restore(tmp_path):
    tr = Trash(tmp_path)
    tr.discard_ticket("S-001", "Buy SSD", "- [ ] S-001 Buy SSD", "plan-x")
    listed = tr.list("plan-x")
    assert len(listed) == 1
    assert listed[0]["ticket_id"] == "S-001"
    rec = tr.restore("plan-x", "S-001")
    assert rec["title"] == "Buy SSD"
    assert tr.list("plan-x") == []


def test_trash_restore_after_restart(tmp_path):
    tr1 = Trash(tmp_path)
    tr1.discard_ticket("S-002", "Do things", "- [ ] S-002 Do things", "plan-y")
    tr2 = Trash(tmp_path)
    assert tr2.restore("plan-y", "S-002") is not None


def test_trash_restore_missing_returns_none(tmp_path):
    tr = Trash(tmp_path)
    assert tr.restore("plan-z", "S-999") is None
