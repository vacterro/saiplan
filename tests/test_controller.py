"""BoardController transactionality (spec 2/3/5): failed mutations leave
memory, disk, history and LOG untouched; conflicts preserve both sides;
recovery adoption is clean."""

import pytest

from saiplan.core.board import render_board
from saiplan.core.config import Config
from saiplan.core.model import DOING, TODO
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


def test_deleted_external_board_keep_mine_recreates_authority(ctx):
    plan, store = ctx
    c = _controller(plan, store)
    c.create_ticket("Local")
    plan.board_path.unlink()
    assert c.resolve_keep_mine() is None
    assert "Local" in plan.board_path.read_text(encoding="utf-8")
    assert c.last_result.committed


def test_deleted_external_board_reload_enters_readonly(ctx):
    plan, store = ctx
    c = _controller(plan, store)
    c.create_ticket("Local")
    plan.board_path.unlink()
    copy_path = c.resolve_reload_external()
    assert copy_path is not None
    assert c.read_only
    assert c.board.all_tickets() == []
    assert "Local" in __import__("pathlib").Path(copy_path).read_text(encoding="utf-8")


def test_invalid_utf8_conflict_copy_is_byte_identical(ctx):
    from saiplan.core.persistence import atomic_write_bytes

    plan, store = ctx
    c = _controller(plan, store)
    c.create_ticket("Local")
    damaged = b"\xff\x00external"
    atomic_write_bytes(plan.board_path, damaged)
    copy_path = c.resolve_keep_mine()
    assert __import__("pathlib").Path(copy_path).read_bytes() == damaged


def test_sidecar_failures_are_warnings_after_board_commit(ctx, monkeypatch):
    plan, store = ctx
    c = _controller(plan, store)

    def fail(*_args, **_kwargs):
        raise OSError("sidecar unavailable")

    monkeypatch.setattr(c.history, "record", fail)
    monkeypatch.setattr("saiplan.ui.controller.append_event", fail)
    ticket = c.create_ticket("Still saved")
    assert c.board.get(ticket.ticket_id) is not None
    assert "Still saved" in plan.board_path.read_text(encoding="utf-8")
    assert c.last_result.committed
    assert len(c.last_result.warnings) == 2


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


def test_deleted_and_undone_ids_are_never_reused(ctx):
    plan, store = ctx
    c = _controller(plan, store)
    first = c.create_ticket("First")
    c.delete_ticket(first.ticket_id)
    assert c.create_ticket("After delete").ticket_id == "S-2"
    assert c.undo()
    assert c.create_ticket("After undo").ticket_id == "S-3"


def test_batch_undo_never_reuses_reserved_range(ctx):
    from saiplan.core.proposal import PlanProposal, TaskProposal

    plan, store = ctx
    c = _controller(plan, store)
    created = c.accept_proposal(
        PlanProposal(goal="g", tasks=[TaskProposal("A"), TaskProposal("B"), TaskProposal("C")])
    )
    assert [ticket.ticket_id for ticket in created] == ["S-1", "S-2", "S-3"]
    assert c.undo()
    assert c.create_ticket("After batch undo").ticket_id == "S-4"


def test_failed_board_commit_still_consumes_reserved_id(ctx):
    plan, store = ctx
    c = _controller(plan, store)
    atomic_write(plan.board_path, render_board(c.board) + "\n")
    with pytest.raises(ControllerError):
        c.create_ticket("Will fail")
    c.resolve_keep_mine()
    assert c.create_ticket("After failed reservation").ticket_id == "S-2"


def test_restart_preserves_id_sequence(ctx):
    plan, store = ctx
    c = _controller(plan, store)
    assert c.create_ticket("First").ticket_id == "S-1"
    c2 = _controller(plan, BoardStore(plan.board_path, plan.history_dir))
    assert c2.create_ticket("Second").ticket_id == "S-2"


@pytest.mark.parametrize("key,value", [("title", "Same"), ("priority", ""), ("details", "")])
def test_unchanged_edits_create_no_history(ctx, key, value):
    plan, store = ctx
    c = _controller(plan, store)
    ticket = c.create_ticket("Same")
    before = len(c.history._read_lines(c.history.undo_path))
    c.edit_field(ticket.ticket_id, key, value)
    assert len(c.history._read_lines(c.history.undo_path)) == before
    assert c.undo()
    assert c.board.get(ticket.ticket_id) is None


def test_controller_enforces_single_focus_and_done_dependencies(ctx):
    plan, store = ctx
    config = Config(plan.directory / "config.json")
    config.set("single_focus", True)
    c = BoardController(plan, store, config)
    c.load()
    first = c.create_ticket("First")
    second = c.create_ticket("Second")
    c.transition(first.ticket_id, DOING)
    with pytest.raises(ControllerError, match="single focus"):
        c.transition(second.ticket_id, DOING)
    with pytest.raises(ControllerError, match="requires dependency"):
        c.edit_field(first.ticket_id, "needs", second.ticket_id)


def test_unblock_and_reopen_emit_distinct_events(ctx):
    plan, store = ctx
    c = _controller(plan, store)
    ticket = c.create_ticket("Ticket")
    c.transition(ticket.ticket_id, "BLOCKED", "waiting")
    c.transition(ticket.ticket_id, "TODO", "ready")
    assert c.last_event == "TICKET_UNBLOCKED"
    c.transition(ticket.ticket_id, "DOING")
    c.transition(ticket.ticket_id, "DONE")
    c.transition(ticket.ticket_id, "TODO")
    assert c.last_event == "TICKET_REOPENED"
    history_count = len(c.history._read_lines(c.history.undo_path))
    c.transition(ticket.ticket_id, "TODO")
    assert c.last_event is None
    assert len(c.history._read_lines(c.history.undo_path)) == history_count


# -- snapshot recovery (T-027) ------------------------------------------


def _alpha_snapshot(store):
    """The snapshot whose board contains Alpha but not Beta."""
    return next(
        p
        for p in store.list_snapshots()
        if "Alpha" in p.read_text(encoding="utf-8") and "Beta" not in p.read_text(encoding="utf-8")
    )


def test_restore_snapshot_is_transactional(ctx):
    plan, store = ctx
    c = _controller(plan, store)
    alpha = c.create_ticket("Alpha")
    beta = c.create_ticket("Beta")
    before_restore = render_board(c.board)
    result = c.restore_snapshot(_alpha_snapshot(store))
    assert result.committed
    assert result.event == "SNAPSHOT_RESTORED"
    assert c.board.get(alpha.ticket_id) is not None
    assert c.board.get(beta.ticket_id) is None
    # current primary backed up byte-exact before the overwrite (I6)
    backups = [p for p in store.list_forensic_copies() if "restore-before" in p.name]
    assert backups
    assert backups[0].read_bytes() == before_restore.encode("utf-8")
    # semantic LOG records the restore
    assert "SNAPSHOT_RESTORED" in plan.log_path.read_text(encoding="utf-8")
    # undo returns to the pre-restore state
    assert c.undo()
    assert render_board(c.board) == before_restore


def test_restore_snapshot_same_state_is_noop(ctx):
    plan, store = ctx
    c = _controller(plan, store)
    c.create_ticket("Alpha")
    newest = store.list_snapshots()[-1]
    assert not c.restore_snapshot(newest).committed
    assert c.last_event is None
    assert not [p for p in store.list_forensic_copies() if "restore-before" in p.name]


def test_restore_snapshot_refuses_invalid_snapshot(ctx):
    plan, store = ctx
    c = _controller(plan, store)
    alpha = c.create_ticket("Alpha")
    bogus = plan.history_dir / "snapshot-bogus.board.md"
    bogus.write_text("## TODO\n- [ ] broken\nno headings", encoding="utf-8")
    with pytest.raises(ControllerError, match="not a trustworthy"):
        c.restore_snapshot(bogus)
    assert not [p for p in store.list_forensic_copies() if "restore-before" in p.name]
    assert c.board.get(alpha.ticket_id) is not None


def test_restore_snapshot_refuses_external_edit(ctx):
    plan, store = ctx
    c = _controller(plan, store)
    c.create_ticket("Alpha")
    c.create_ticket("Beta")
    target = _alpha_snapshot(store)
    # external edit behind the controller's back
    atomic_write(
        plan.board_path,
        render_board(c.board).replace("## BLOCKED", "- [ ] S-999 External\n## BLOCKED"),
    )
    with pytest.raises(ControllerError, match="externally"):
        c.restore_snapshot(target)
    # A harmless forensic backup may be left behind (P0-2)
    assert c.board.counts()[TODO] == 2


def test_restore_snapshot_readonly_plan_refused(ctx):
    plan, store = ctx
    c = _controller(plan, store)
    c.create_ticket("Alpha")
    target = store.list_snapshots()[-1]
    for s in store.history_dir.glob("snapshot-*"):
        atomic_write(s, "garbage")
    atomic_write(plan.board_path, "TOTAL GARBAGE PRIMARY")
    c2 = _controller(plan, store)
    assert c2.read_only
    with pytest.raises(ControllerError, match="read-only"):
        c2.restore_snapshot(target)


def test_recovery_artifacts_listing(ctx):
    plan, store = ctx
    c = _controller(plan, store)
    c.create_ticket("Alpha")
    c.create_ticket("Beta")
    store.preserve_raw_corrupt(b"\xff\xfe raw corrupt bytes")
    artifacts = c.recovery_artifacts()
    kinds = {a["kind"] for a in artifacts}
    assert "snapshot" in kinds and "corrupt" in kinds
    snaps = [a for a in artifacts if a["kind"] == "snapshot"]
    assert snaps and all(a["valid"] for a in snaps)
    assert all(a["summary"] for a in snaps)
    corrupt = [a for a in artifacts if a["kind"] == "corrupt"]
    assert corrupt and corrupt[0]["summary"] == "unreadable"
    # a restore surfaces a restore-before backup in the listing
    c.restore_snapshot(_alpha_snapshot(store))
    assert "restore-before" in {a["kind"] for a in c.recovery_artifacts()}
