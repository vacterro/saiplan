"""BoardController transactionality (spec 2/3/5): failed mutations leave
memory, disk, history and LOG untouched; conflicts preserve both sides;
recovery adoption is clean."""

import pytest

from saiplan.core.board import render_board
from saiplan.core.persistence import BoardStore, atomic_write
from saiplan.core.plan import PlanStore
from saiplan.ui.controller import BoardController, ControllerError


@pytest.fixture
def ctx(tmp_path):
    store = PlanStore(tmp_path / "plans")
    plan = store.create("Txn Plan")
    return plan, BoardStore(plan.board_path, plan.history_dir)


def _controller(plan, store):
    c = BoardController(plan, store)
    c.load()
    return c


def test_failed_mutation_leaves_board_and_disk_unchanged(ctx):
    plan, store = ctx
    c = _controller(plan, store)
    c.create_ticket("Original")
    before = render_board(c.board)
    history_before = c.history.can_undo()
    # externally modify the primary -> the next save must be refused
    ext = render_board(c.board).replace("## BLOCKED", "- [ ] S-999 External\n## BLOCKED")
    atomic_write(plan.board_path, ext)
    assert c.has_external_change()
    with pytest.raises(ControllerError):
        c.create_ticket("unsaved mutation")
    # memory unchanged
    assert c.board.get("unsaved mutation") is None
    assert render_board(c.board) == before
    # disk unchanged
    assert "unsaved mutation" not in plan.board_path.read_text(encoding="utf-8")
    # history unchanged
    assert c.history.can_undo() == history_before


def test_failed_edit_leaves_disk_memory_history_unchanged(ctx):
    plan, store = ctx
    c = _controller(plan, store)
    c.create_ticket("Ticket one")
    tid = c.board.all_tickets()[0].ticket_id
    history_lines = len(c.history._read_lines(c.history.undo_path))
    ext = render_board(c.board).replace("## BLOCKED", "- [ ] S-999 External\n## BLOCKED")
    atomic_write(plan.board_path, ext)
    assert c.has_external_change()
    with pytest.raises(ControllerError):
        c.edit_field(tid, "priority", "high")
    assert c.board.get(tid).get("priority") == ""
    assert "priority" not in plan.board_path.read_text(encoding="utf-8")
    assert len(c.history._read_lines(c.history.undo_path)) == history_lines


def test_external_edit_blocks_undo_and_stacks_untouched(ctx):
    plan, store = ctx
    c = _controller(plan, store)
    c.create_ticket("First")
    c.create_ticket("Second")
    assert c.history.can_undo()
    ext = render_board(c.board).replace("## BLOCKED", "- [ ] S-999 External\n## BLOCKED")
    atomic_write(plan.board_path, ext)
    with pytest.raises(ControllerError):
        c.undo()
    # stacks unchanged
    assert c.history.can_undo()
    assert not c.history.can_redo()
    assert c.board.get("S-999") is None


def test_undo_redo_transactional(ctx):
    plan, store = ctx
    c = _controller(plan, store)
    c.create_ticket("First")
    c.create_ticket("Second")
    assert c.undo()
    assert c.board.all_tickets()[0].title == "First"
    assert c.redo()
    assert len(c.board.all_tickets()) == 2


def test_keep_mine_preserves_external_bytes(ctx):
    plan, store = ctx
    c = _controller(plan, store)
    c.create_ticket("Local ticket")
    ext = render_board(c.board).replace("## BLOCKED", "- [ ] S-999 External edit\n## BLOCKED")
    atomic_write(plan.board_path, ext)
    assert c.has_external_change()
    copy_path = c.resolve_keep_mine()
    assert copy_path is not None
    # external bytes survived in the conflict copy
    with open(copy_path, encoding="utf-8") as fh:
        assert "S-999 External edit" in fh.read()
    # canonical now holds the local version
    assert "Local ticket" in plan.board_path.read_text(encoding="utf-8")
    assert not c.has_external_change()


def test_reload_external_preserves_local_bytes(ctx):
    plan, store = ctx
    c = _controller(plan, store)
    c.create_ticket("Local ticket")
    ext = render_board(c.board).replace("## BLOCKED", "- [ ] S-999 External edit\n## BLOCKED")
    atomic_write(plan.board_path, ext)
    copy_path = c.resolve_reload_external()
    assert copy_path is not None
    # local bytes preserved in the conflict-local copy
    with open(copy_path, encoding="utf-8") as fh:
        assert "Local ticket" in fh.read()
    # canonical now holds the external version
    assert "S-999 External edit" in plan.board_path.read_text(encoding="utf-8")
    assert c.board.get("S-999") is not None
    assert not c.has_external_change()


def test_missing_board_recovers_snapshot(ctx):
    plan, store = ctx
    c = _controller(plan, store)
    c.create_ticket("Golden")
    plan.board_path.unlink()
    c2 = _controller(plan, store)
    assert c2.board.all_tickets()[0].title == "Golden"
    assert not c2.read_only
    assert plan.board_path.exists()


def test_corrupt_board_without_snapshot_is_readonly(ctx):
    plan, store = ctx
    c = _controller(plan, store)
    c.create_ticket("Golden")
    for s in store.history_dir.glob("snapshot-*"):
        atomic_write(s, "garbage")
    atomic_write(plan.board_path, "TOTAL GARBAGE PRIMARY")
    c2 = _controller(plan, store)
    assert c2.read_only
    with pytest.raises(ControllerError):
        c2.create_ticket("refused")
    # primary untouched
    assert "TOTAL GARBAGE PRIMARY" in plan.board_path.read_text(encoding="utf-8")


def test_delete_then_restore_keeps_trash_on_failed_save(ctx):
    plan, store = ctx
    c = _controller(plan, store)
    t = c.create_ticket("Doomed")
    c.delete_ticket(t.ticket_id)
    assert c.board.get(t.ticket_id) is None
    # now an external edit blocks the restore save
    atomic_write(
        plan.board_path, render_board(c.board).replace("## BLOCKED", "- [ ] S-999 Ext\n## BLOCKED")
    )
    with pytest.raises(ControllerError):
        c.restore_ticket(t.ticket_id)
    # trash record NOT consumed
    from saiplan.core.history import Trash

    rec = Trash(plan.history_dir).peek(plan.plan_id, t.ticket_id)
    assert rec is not None


def test_restore_duplicate_id_keeps_trash_record(ctx):
    plan, store = ctx
    from saiplan.core.history import Trash

    # the board already contains S-001
    store.load()  # establish guard against the empty board written by create()
    store.save("## TODO\n- [ ] S-001 Existing\n## DOING\n## DONE\n## BLOCKED\n")
    Trash(plan.history_dir).discard_ticket("S-001", "Old", "- [ ] S-001 Old", plan.plan_id)
    c = _controller(plan, store)
    with pytest.raises(ControllerError):
        c.restore_ticket("S-001")
    # trash record was NOT consumed
    assert Trash(plan.history_dir).peek(plan.plan_id, "S-001") is not None


def test_readonly_plan_refuses_mutation(ctx):
    plan, store = ctx
    c = _controller(plan, store)
    c.create_ticket("Golden")
    for s in store.history_dir.glob("snapshot-*"):
        atomic_write(s, "garbage")
    atomic_write(plan.board_path, "GARBAGE")
    c2 = _controller(plan, store)
    assert c2.read_only
    with pytest.raises(ControllerError):
        c2.create_ticket("refused")
    with pytest.raises(ControllerError):
        c2.undo()
    with pytest.raises(ControllerError):
        c2.redo()
