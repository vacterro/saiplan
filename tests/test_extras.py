"""Extras: notes/backlinks, statistics, archive."""

import pytest

from saiplan.core.lifecycle import create_ticket
from saiplan.core.model import Board
from saiplan.core.plan import PlanStore
from saiplan.extras import archive, notes, statistics
from saiplan.extras.timers import TicketTimer


@pytest.fixture
def plan(tmp_path):
    return PlanStore(tmp_path / "plans").create("Stats Plan")


def test_note_write_read(plan):
    path = notes.write_note(plan, "S-001 Review", "# S-001\n\nshipped [[S-002]]\n")
    assert path.exists()
    assert "shipped" in notes.read_note(path)
    assert notes.ticket_links(notes.read_note(path)) == ["S-002"]


def test_backlinks_found(plan):
    notes.write_note(plan, "note-a", "blocked by [[S-007]]")
    notes.write_note(plan, "note-b", "nothing here")
    bl = notes.backlinks(plan, "S-007")
    assert len(bl) == 1
    assert "note-a" in bl[0].name


def test_backlinks_require_exact_wikilink(plan):
    notes.write_note(plan, "plain", "mentions S-007 without a link")
    assert notes.backlinks(plan, "S-007") == []


def test_reserved_note_name_is_safe(plan):
    assert notes.write_note(plan, "CON", "x").name == "note-CON.md"


def test_notes_unicode_names_preserved_and_atomic(plan):
    """Multilingual note names keep their Unicode (no collapse to 'note');
    writes are atomic (no temp litter)."""
    path = notes.write_note(plan, "Моя заметка / 私のメモ", "content")
    assert path.exists()
    assert "Моя" in path.name and "私" in path.name
    assert notes.read_note(path) == "content"
    assert list(plan.notes_dir.glob("*.tmp-*")) == []


def test_note_name_collision_free(plan):
    a = notes.write_note(plan, "Русский", "one")
    b = notes.write_note(plan, "日本語", "two")
    assert a != b
    assert a.exists() and b.exists()


def test_note_search(plan):
    notes.write_note(plan, "one", "buy the ssd now")
    notes.write_note(plan, "two", "other stuff")
    hits = notes.note_search(plan, "ssd")
    assert [p.name for p in hits] == ["one.md"]


def test_statistics_counts(plan):
    board = Board()
    create_ticket(board, "Task")
    from saiplan.core.board import render_board

    plan.board_path.write_text(render_board(board), encoding="utf-8")
    counts = statistics.status_totals(plan)
    assert counts["TODO"] == 1


def test_statistics_time_spent(plan):
    import time

    tt = TicketTimer(plan.timelog_path)
    sid = tt.start("S-001")
    time.sleep(0.02)
    tt.stop(sid)
    assert statistics.total_time(plan) > 0
    assert statistics.time_spent(plan, "S-001") > 0


def test_statistics_activity_from_log(plan):
    from saiplan.core.logbook import append_event

    append_event(plan.log_path, "TICKET_DONE", ticket="S-001")
    append_event(plan.log_path, "TICKET_DONE", ticket="S-002")
    append_event(plan.log_path, "PLAN_REVIEWED")
    act = statistics.activity_counts(plan)
    assert act["TICKET_DONE"] == 2
    assert act["PLAN_REVIEWED"] == 1


def test_statistics_rejects_corrupt_board_and_timelog(plan):
    plan.board_path.write_text(
        "## TODO\n## HUMAN\n## DOING\n## DONE\n## BLOCKED\n", encoding="utf-8"
    )
    assert statistics.status_totals(plan) == {}
    plan.timelog_path.write_text(
        '[]\n{"kind":"ticket","session_id":"a","ended_at":"x","duration_s":"banana"}\n'
        '{"kind":"ticket","session_id":"b","ended_at":"x","duration_s":-2}\n'
        '{"kind":"ticket","session_id":"c","ended_at":"x","duration_s":3}\n'
        '{"kind":"ticket","session_id":"c","ended_at":"x","duration_s":3}\n',
        encoding="utf-8",
    )
    assert statistics.total_time(plan) == 3.0


def test_archive_move_and_restore(plan, tmp_path):
    plans_dir = plan.directory.parent
    archived = archive.archive_plan(plans_dir, plan.plan_id)
    assert archived is not None
    assert not plan.directory.exists()
    assert archived.exists()
    assert archive.list_archived(plans_dir) == [archived]
    restored = archive.restore_plan(plans_dir, archived)
    assert restored is not None
    assert restored.exists()
    assert (restored / "PLAN.md").exists()
