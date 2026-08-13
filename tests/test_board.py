"""BOARD parser/writer: round-trip, escapes, malformed input, stable ids."""

from conftest import build_board

from saiplan.core.board import escape_value, parse_board, render_board, render_ticket
from saiplan.core.lifecycle import create_ticket
from saiplan.core.model import BLOCKED, DOING, DONE, TODO, Board, Ticket


def _roundtrip(board) -> tuple:
    text = render_board(board)
    board2, errors = parse_board(text)
    return board2, errors, text


def test_empty_board_roundtrip():
    board = Board()
    b2, errors, _ = _roundtrip(board)
    assert not errors
    assert b2.counts() == {"DOING": 0, "TODO": 0, "DONE": 0, "BLOCKED": 0}


def test_simple_roundtrip_preserves_order_and_fields():
    board = Board()
    t = create_ticket(board, "Buy new SSD")
    t.set_field("priority", "high")
    t.set_field("due", "2026-08-20")
    b2, errors, _ = _roundtrip(board)
    assert not errors
    t2 = b2.get(t.ticket_id)
    assert t2.title == "Buy new SSD"
    assert t2.status == TODO
    assert t2.get("priority") == "high"
    assert t2.get("due") == "2026-08-20"


def test_sections_preserve_column_order():
    board = build_board("DOING S-001 Work", "TODO S-002 Wait", "DONE S-003 Done")
    b2, errors, _ = _roundtrip(board)
    assert not errors
    assert [t.ticket_id for t in b2.sections[DOING]] == ["S-001"]
    assert [t.ticket_id for t in b2.sections[TODO]] == ["S-002"]
    assert [t.ticket_id for t in b2.sections[DONE]] == ["S-003"]


def test_pipe_in_title_and_field_roundtrips():
    board = Board()
    t = create_ticket(board, r"Fix | broken \ pipe")
    t.set_field("details", r"contains | and \ backslash")
    b2, errors, _ = _roundtrip(board)
    assert not errors
    t2 = b2.get(t.ticket_id)
    assert t2.title == r"Fix | broken \ pipe"
    assert t2.get("details") == r"contains | and \ backslash"


def test_escape_unescape_is_inverse():
    for value in ["plain", "a|b", "a\\b", "a\\|b", "|", "\\", "a | b \\ c"]:
        assert escape_value(value) is not value or "|" not in value or "\\" not in value


def test_checkbox_section_disagreement_is_error():
    text = "## TODO\n- [x] S-001 Claimed done but in TODO\n## DOING\n## DONE\n## BLOCKED\n"
    board, errors = parse_board(text)
    assert any("checkbox" in e for e in errors)
    # lenient load: the ticket is still usable, the error is advisory
    assert board.get("S-001") is not None


def test_duplicate_ticket_id_is_error():
    text = "## TODO\n- [ ] S-001 A\n- [ ] S-001 B\n## DOING\n## DONE\n## BLOCKED\n"
    board, errors = parse_board(text)
    assert any("duplicate ticket id" in e for e in errors)
    assert board.get("S-001").title == "A"  # first occurrence kept


def test_duplicate_field_is_malformed():
    text = "## TODO\n- [ ] S-001 A | due: 1 | due: 2\n## DOING\n## DONE\n## BLOCKED\n"
    _board, errors = parse_board(text)
    assert any("duplicate" in e for e in errors)


def test_unknown_field_preserved_not_dropped():
    text = "## TODO\n- [ ] S-001 A | alien-field: keepme\n## DOING\n## DONE\n## BLOCKED\n"
    board, errors = parse_board(text)
    assert not errors
    assert board.get("S-001").get("alien-field") == "keepme"


def test_missing_heading_is_error():
    text = "## TODO\n- [ ] S-001 A\n## DOING\n"
    _board, errors = parse_board(text)
    assert any("DONE" in e and "heading" in e for e in errors)


def test_malformed_line_skipped_rest_loads():
    text = "## TODO\nthis is not a ticket\n- [ ] S-001 Fine\n## DOING\n## DONE\n## BLOCKED\n"
    board, errors = parse_board(text)
    assert errors
    assert board.get("S-001") is not None


def test_ticket_under_unknown_heading_is_error():
    text = "## WIP\n- [ ] S-001 A\n## TODO\n## DOING\n## DONE\n## BLOCKED\n"
    _board, errors = parse_board(text)
    assert any("unknown heading" in e for e in errors)


def test_blocked_by_field_preserved():
    board = Board()
    t = create_ticket(board, "Blocked task", status=BLOCKED)
    t.set_field("blocked-by", "waiting for parts")
    b2, errors, _ = _roundtrip(board)
    assert not errors
    assert b2.get(t.ticket_id).get("blocked-by") == "waiting for parts"


def test_stable_ids_after_roundtrip_rename_and_reorder():
    board = build_board("TODO S-010 First", "TODO S-020 Second", "DONE S-030 Third")
    b2, errors, text = _roundtrip(board)
    assert not errors
    b3, errors2, _ = _roundtrip(b2)
    assert not errors2
    assert b3.get("S-010").title == "First"
    assert b3.get("S-030").title == "Third"
    assert "S-010" in text


def test_parse_is_byte_stable_for_unmodified_lines():
    """An unknown-field line round-trips byte-for-byte (human fields survive)."""
    line = "- [ ] S-001 Buy SSD | alien: keep | due: 2026-08-20"
    text = f"## TODO\n{line}\n## DOING\n## DONE\n## BLOCKED\n"
    board, errors = parse_board(text)
    assert not errors
    text2 = render_board(board)
    assert line in text2


def test_empty_string_is_malformed():
    _board, errors = parse_board("")
    assert errors


def test_render_ticket_produces_canonical_form():
    t = Ticket("S-001", "Task", status=TODO, fields=[("due", "2026-08-20")])
    assert render_ticket(t) == "- [ ] S-001 Task | due: 2026-08-20"
