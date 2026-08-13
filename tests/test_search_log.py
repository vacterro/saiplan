"""Search index + semantic log."""

from conftest import build_board

from saiplan.core.logbook import append_event, read_log, ticket_ids_in_log
from saiplan.core.search import Searcher


def test_search_finds_by_id_title_and_field():
    board = build_board("TODO S-001 Buy an SSD disk", "DONE S-002 Clean desk")
    board.get("S-001").set_field("priority", "urgent")
    se = Searcher()
    se.refresh(board)
    assert se.search("ssd") == [{"id": "S-001"}]
    assert se.search("s-002") == [{"id": "S-002"}]
    assert se.search("urgent") == [{"id": "S-001"}]
    assert se.search("clean desk") == [{"id": "S-002"}]
    assert len(se.search("")) == 2
    assert se.search("missing-term") == []


def test_search_multi_term_and():
    board = build_board("TODO S-001 Buy SSD disk", "TODO S-002 Buy RAM")
    se = Searcher()
    se.refresh(board)
    assert se.search("buy ssd") == [{"id": "S-001"}]
    assert se.search("buy ram") == [{"id": "S-002"}]


def test_log_append_and_read_roundtrip(tmp_path):
    log = tmp_path / "LOG.md"
    append_event(log, "PLAN_CREATED", detail="created new plan")
    append_event(log, "TICKET_DONE", ticket="S-001", detail="verified")
    entries = read_log(log)
    assert len(entries) == 2
    assert entries[0]["event"] == "PLAN_CREATED"
    assert entries[1]["ticket"] == "S-001"
    assert entries[1]["detail"] == "verified"


def test_log_rejects_unknown_event(tmp_path):
    import pytest

    with pytest.raises(ValueError):
        append_event(tmp_path / "LOG.md", "MOUSE_FART")


def test_torn_log_tail_skipped(tmp_path):
    log = tmp_path / "LOG.md"
    append_event(log, "PLAN_CREATED")
    with open(log, "a", encoding="utf-8") as fh:
        fh.write("- 2026-08-13T00:00:00Z TIC")  # torn line
    assert len(read_log(log)) == 1


def test_ticket_ids_in_log():
    assert ticket_ids_in_log("did S-12 then S-7") == ["S-12", "S-7"]
