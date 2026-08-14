"""Ticket attachments (T-029): safe names, no overwrite, remove -> trash,
ticket delete/reopen never loses them, bundles carry them."""

import shutil

import pytest

from saiplan.core.attachments import Attachments, safe_attachment_name
from saiplan.core.bundle import export_plan, import_plan
from saiplan.core.persistence import BoardStore
from saiplan.core.plan import PlanStore
from saiplan.ui.controller import BoardController, ControllerError


@pytest.fixture
def ctx(tmp_path):
    store = PlanStore(tmp_path / "plans")
    plan = store.create("Attach Plan")
    c = BoardController(plan, BoardStore(plan.board_path, plan.history_dir))
    c.load()
    return plan, c


def _source(tmp_path, name="report.pdf", data=b"pdf-bytes"):
    source = tmp_path / name
    source.write_bytes(data)
    return source


def test_safe_attachment_name_strips_path_and_unsafe_chars():
    assert safe_attachment_name("../../evil.txt") == "evil.txt"
    assert safe_attachment_name(r"C:\\temp\\a:b?.txt") == "a_b_.txt"
    assert safe_attachment_name("con.txt") == "attachment-con.txt"
    assert safe_attachment_name("   ") == "attachment"


def test_attach_copies_with_safe_name_and_keeps_original(tmp_path, ctx):
    plan, c = ctx
    ticket = c.create_ticket("Needs file")
    source = _source(tmp_path, "my report (final).pdf")
    target = c.attach_file(ticket.ticket_id, source)
    assert target.name == "my report (final).pdf"
    assert target.read_bytes() == b"pdf-bytes"
    assert source.read_bytes() == b"pdf-bytes"  # original untouched (copy, not move)
    assert target.parent == plan.directory / "attachments" / ticket.ticket_id


def test_attach_never_overwrites_on_collision(tmp_path, ctx):
    _plan, c = ctx
    ticket = c.create_ticket("Collisions")
    a = _source(tmp_path, "plan.pdf", b"one")
    b = _source(tmp_path, "plan2.pdf", b"two")
    first = c.attach_file(ticket.ticket_id, a, dest_name="plan.pdf")
    second = c.attach_file(ticket.ticket_id, b, dest_name="plan.pdf")
    assert first.read_bytes() == b"one"
    assert second.read_bytes() == b"two"
    assert second.name == "plan-1.pdf"
    assert len(c.list_attachments(ticket.ticket_id)) == 2


def test_list_is_sorted(ctx):
    plan, c = ctx
    ticket = c.create_ticket("Sorted")
    for name in ("zebra.txt", "alpha.txt", "mike.txt"):
        source = _source(plan.directory.parent, name, name.encode())
        c.attach_file(ticket.ticket_id, source, dest_name=name)
    assert [p.name for p in c.list_attachments(ticket.ticket_id)] == [
        "alpha.txt",
        "mike.txt",
        "zebra.txt",
    ]


def test_remove_moves_to_trash_byte_exact_and_repeats_suffix(tmp_path, ctx):
    plan, c = ctx
    ticket = c.create_ticket("Removable")
    c.attach_file(ticket.ticket_id, _source(tmp_path, "draft.docx", b"draft-bytes"))
    trash = c.remove_attachment(ticket.ticket_id, "draft.docx")
    assert trash.parent == plan.history_dir / "attachments-trash" / ticket.ticket_id
    assert trash.read_bytes() == b"draft-bytes"
    assert c.list_attachments(ticket.ticket_id) == []
    # removing a same-named file again never overwrites the trash record
    c.attach_file(
        ticket.ticket_id, _source(tmp_path, "again.docx", b"second"), dest_name="draft.docx"
    )
    second_trash = c.remove_attachment(ticket.ticket_id, "draft.docx")
    assert second_trash.parent == trash.parent
    assert second_trash.name == "draft-1.docx"
    assert second_trash.read_bytes() == b"second"


def test_remove_missing_attachment_raises(ctx):
    _plan, c = ctx
    ticket = c.create_ticket("Empty")
    with pytest.raises(FileNotFoundError):
        c.remove_attachment(ticket.ticket_id, "nope.txt")


def test_ticket_delete_and_restore_keep_attachments(tmp_path, ctx):
    _plan, c = ctx
    ticket = c.create_ticket("Doomed but preserved")
    c.attach_file(ticket.ticket_id, _source(tmp_path, "keep.me"))
    c.delete_ticket(ticket.ticket_id)
    # attachments stay on disk while the ticket is in trash
    assert len(c.list_attachments(ticket.ticket_id)) == 1
    c.restore_ticket(ticket.ticket_id)
    assert c.board.get(ticket.ticket_id) is not None
    assert [p.name for p in c.list_attachments(ticket.ticket_id)] == ["keep.me"]


def test_undo_delete_keeps_attachments(tmp_path, ctx):
    _plan, c = ctx
    ticket = c.create_ticket("Undo me")
    c.attach_file(ticket.ticket_id, _source(tmp_path, "undone.txt"))
    c.delete_ticket(ticket.ticket_id)
    assert c.undo()
    assert [p.name for p in c.list_attachments(ticket.ticket_id)] == ["undone.txt"]


def test_bundle_round_trip_carries_attachments(tmp_path, ctx):
    plan, c = ctx
    ticket = c.create_ticket("Portable")
    c.attach_file(ticket.ticket_id, _source(tmp_path, "spec.pdf", b"spec-bytes"))
    bundle = tmp_path / "attached.saiplan"
    export_plan(plan, bundle)
    shutil.rmtree(plan.directory)
    imported = import_plan(tmp_path / "plans", bundle)
    path = imported.directory / "attachments" / ticket.ticket_id / "spec.pdf"
    assert path.read_bytes() == b"spec-bytes"


def test_controller_refuses_attach_to_unknown_ticket(tmp_path, ctx):
    _plan, c = ctx
    with pytest.raises(ControllerError, match="no such ticket"):
        c.attach_file("S-999", _source(tmp_path, "x.txt"))


def test_attachments_are_sidecars_never_board_authority(tmp_path, ctx):
    plan, c = ctx
    ticket = c.create_ticket("Sidecar")
    before = plan.board_path.read_bytes()
    c.attach_file(ticket.ticket_id, _source(tmp_path, "side.txt"))
    assert plan.board_path.read_bytes() == before  # BOARD.md untouched
    assert Attachments(plan).directory.exists()
