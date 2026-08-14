"""Persisted undo/redo + trash (survive restart, spec 9/19).

History is transactional: peek inspects without moving stacks; commit moves a
record only after the board was persisted. Trash identity is an immutable
record_id — two deletes in the same second stay independent.
"""

from conftest import build_board

from saiplan.core.board import render_board
from saiplan.core.history import UNDO_CAP, History, IdSequence, Trash


def _mk(h, *sections):
    """Record ops on empty texts."""


def test_peek_undo_does_not_move_stacks(tmp_path):
    h = History(tmp_path)
    a = render_board(build_board("TODO S-001 A"))
    b = render_board(build_board("TODO S-002 B"))
    h.record("create", a, b)
    assert h.can_undo()
    assert not h.can_redo()
    rec = h.peek_undo(b)
    assert rec is not None
    assert rec["prev"] == a
    # stacks untouched after peek
    assert len(h._read_lines(h.undo_path)) == 1
    assert len(h._read_lines(h.redo_path)) == 0


def test_commit_undo_moves_record(tmp_path):
    h = History(tmp_path)
    a = render_board(build_board("TODO S-001 A"))
    b = render_board(build_board("TODO S-002 B"))
    h.record("create", a, b)
    rec = h.peek_undo(b)
    h.commit_undo(rec["record_id"])
    assert len(h._read_lines(h.undo_path)) == 0
    assert len(h._read_lines(h.redo_path)) == 1
    # redo can now peek it
    rec2 = h.peek_redo(a)
    assert rec2 is not None and rec2["after"] == b


def test_commit_redo_returns_record(tmp_path):
    h = History(tmp_path)
    a = render_board(build_board("TODO S-001 A"))
    b = render_board(build_board("TODO S-002 B"))
    h.record("create", a, b)
    rec = h.peek_undo(b)
    h.commit_undo(rec["record_id"])
    rec2 = h.peek_redo(a)
    h.commit_redo(rec2["record_id"])
    assert len(h._read_lines(h.undo_path)) == 1
    assert len(h._read_lines(h.redo_path)) == 0


def test_history_survives_restart(tmp_path):
    h1 = History(tmp_path)
    a = render_board(build_board("TODO S-001 A"))
    b = render_board(build_board("TODO S-002 B"))
    h1.record("create", a, b)
    h2 = History(tmp_path)  # restart
    rec = h2.peek_undo(b)
    assert rec["prev"] == a
    h2.commit_undo(rec["record_id"])
    h3 = History(tmp_path)
    assert h3.peek_redo(a)["after"] == b


def test_new_mutation_clears_redo(tmp_path):
    h = History(tmp_path)
    a = render_board(build_board("TODO S-001 A"))
    b = render_board(build_board("TODO S-002 B"))
    c = render_board(build_board("TODO S-003 C"))
    h.record("create", a, b)
    rec = h.peek_undo(b)
    h.commit_undo(rec["record_id"])
    h.record("create", a, c)  # new mutation invalidates redo
    assert not h.can_redo()


def test_undo_capped(tmp_path):
    h = History(tmp_path)
    for i in range(UNDO_CAP + 40):
        h.record(f"op{i}", f"prev{i}", f"after{i}")
    h2 = History(tmp_path)
    assert len(h2._read_lines(h2.undo_path)) == UNDO_CAP


def test_corrupt_line_skipped(tmp_path):
    h = History(tmp_path)
    (tmp_path / "undo.jsonl").write_text("not json\n", encoding="utf-8")
    assert h.peek_undo("x") is None
    assert not h.can_undo()


def test_missing_required_keys_skipped(tmp_path):
    h = History(tmp_path)
    (tmp_path / "undo.jsonl").write_text(
        '{"seq":1,"op":"x"}\n{"prev":"a","after":"b"}\n', encoding="utf-8"
    )
    recs = h._read_lines(h.undo_path)
    assert len(recs) == 1  # the well-formed one survives
    # prev==a matches current -> skipped
    assert h.peek_undo("a") is None
    assert h.peek_undo("b")["prev"] == "a"


def test_legacy_noop_history_pruned_on_restart(tmp_path):
    path = tmp_path / "undo.jsonl"
    path.write_text(
        '{"prev":"same","after":"same"}\n{"prev":"before","after":"after"}\n',
        encoding="utf-8",
    )
    h = History(tmp_path)
    records = h._read_lines(path)
    assert len(records) == 1
    assert records[0]["record_id"]
    assert h.peek_undo("after")["record_id"] == records[0]["record_id"]


def test_commit_requires_exact_peeked_record(tmp_path):
    h = History(tmp_path)
    h.record("create", "a", "b")
    rec = h.peek_undo("b")
    with __import__("pytest").raises(RuntimeError):
        h.commit_undo("not-the-peeked-record")
    assert h.peek_undo("b")["record_id"] == rec["record_id"]


def test_duplicate_legacy_record_ids_are_migrated(tmp_path):
    duplicate = "same-id"
    (tmp_path / "undo.jsonl").write_text(
        f'{{"record_id":"{duplicate}","prev":"a","after":"b"}}\n'
        f'{{"record_id":"{duplicate}","prev":"b","after":"c"}}\n',
        encoding="utf-8",
    )
    records = History(tmp_path)._read_lines(tmp_path / "undo.jsonl")
    assert len({record["record_id"] for record in records}) == 2


def test_id_sequence_self_heals_and_stays_ahead(tmp_path):
    board = tmp_path / "BOARD.md"
    log = tmp_path / "LOG.md"
    history = tmp_path / ".history"
    history.mkdir()
    board.write_text("## TODO\n- [ ] S-9 Existing\n", encoding="utf-8")
    log.write_text("mentions T-4\n", encoding="utf-8")
    sequence = IdSequence(history, board, log)
    assert sequence.reserve() == ["S-10"]
    board.write_text("## TODO\n", encoding="utf-8")
    assert sequence.reserve() == ["S-11"]
    assert sequence.reserve(prefix="T") == ["T-5"]


def test_id_sequence_recovers_from_corruption_using_history_and_trash(tmp_path):
    board = tmp_path / "BOARD.md"
    log = tmp_path / "LOG.md"
    history = tmp_path / ".history"
    history.mkdir()
    board.write_text("## TODO\n", encoding="utf-8")
    log.write_text("# LOG\n", encoding="utf-8")
    (history / "undo.jsonl").write_text('{"prev":"S-12","after":"S-13"}\n', encoding="utf-8")
    (history / "trash.jsonl").write_text('{"ticket_id":"S-15"}\n', encoding="utf-8")
    (history / "id-sequence.json").write_text("{broken", encoding="utf-8")
    assert IdSequence(history, board, log).reserve() == ["S-16"]


def test_id_sequence_ignores_unbounded_integer_token(tmp_path):
    board = tmp_path / "BOARD.md"
    log = tmp_path / "LOG.md"
    history = tmp_path / ".history"
    history.mkdir()
    board.write_text("S-" + "9" * 5000, encoding="utf-8")
    log.write_text("# LOG\n", encoding="utf-8")
    assert IdSequence(history, board, log).reserve() == ["S-1"]


def test_trash_two_deletes_same_second_independent(tmp_path):
    tr = Trash(tmp_path)
    id1 = tr.discard_ticket("S-001", "One", "- [ ] S-001 One", "plan-x")
    id2 = tr.discard_ticket("S-002", "Two", "- [ ] S-002 Two", "plan-x")
    assert id1 != id2
    assert len(tr.list("plan-x")) == 2
    # restore S-001 by record id only removes that one record
    assert tr.mark_restored(id1) is True
    remaining = tr.list("plan-x")
    assert len(remaining) == 1
    assert remaining[0]["ticket_id"] == "S-002"


def test_trash_peek_does_not_consume(tmp_path):
    tr = Trash(tmp_path)
    tr.discard_ticket("S-001", "One", "- [ ] S-001 One", "plan-y")
    rec = tr.peek("plan-y", "S-001")
    assert rec["ticket_id"] == "S-001"
    assert len(tr.list("plan-y")) == 1  # still there after peek


def test_trash_mark_restored_duplicate_is_idempotent(tmp_path):
    tr = Trash(tmp_path)
    rid = tr.discard_ticket("S-001", "One", "- [ ] S-001 One", "plan-z")
    assert tr.mark_restored(rid) is True
    assert tr.mark_restored(rid) is False  # already gone -> reported, no crash
    assert tr.list("plan-z") == []


def test_trash_restore_after_restart(tmp_path):
    tr1 = Trash(tmp_path)
    tr1.discard_ticket("S-002", "Do things", "- [ ] S-002 Do things", "plan-w")
    tr2 = Trash(tmp_path)
    assert tr2.peek("plan-w", "S-002") is not None


def test_trash_peek_missing_returns_none(tmp_path):
    tr = Trash(tmp_path)
    assert tr.peek("plan-v", "S-999") is None
