"""Plan Review advisory checks (spec 5): warn, never block."""

from conftest import build_board

from saiplan.core.model import Board
from saiplan.core.review import WARN, review_board, vague_title


def _by_id(findings):
    return {f[1]: f for f in findings if f[1]}


def test_empty_plan_warns():
    findings = review_board(Board())
    assert any("empty plan" in m for _s, _i, m in findings)


def test_duplicate_titles_warn():
    board = build_board("TODO S-001 Buy SSD", "TODO S-002 Buy SSD")
    findings = review_board(board)
    assert any("duplicate" in m for _s, _i, m in findings)


def test_circular_dependency_warned():
    board = build_board("TODO S-001 A", "TODO S-002 B")
    board.get("S-001").set_field("needs", "S-002")
    board.get("S-002").set_field("needs", "S-001")
    findings = review_board(board)
    assert any("circular" in m for _s, _i, m in findings)


def test_dangling_dependency_warned():
    board = build_board("TODO S-001 A")
    board.get("S-001").set_field("needs", "S-999")
    findings = review_board(board)
    assert any("does not exist" in m for _s, _i, m in findings)


def test_unmet_dependency_warned():
    board = build_board("TODO S-001 A", "TODO S-002 B")
    board.get("S-002").set_field("needs", "S-001")
    findings = review_board(board)
    assert any("not DONE" in m for _s, _i, m in findings)


def test_vague_title_warned():
    assert vague_title("do stuff") is True
    assert vague_title("Replace the hard drive in the laptop") is False
    board = build_board("TODO S-001 do stuff")
    findings = review_board(board)
    assert any("vague" in m for _s, _i, m in findings)


def test_multiple_doing_warned_in_single_focus():
    board = build_board("DOING S-001 A", "DOING S-002 B")
    findings = review_board(board, single_focus=True)
    assert any("multiple tickets in DOING" in m for _s, _i, m in findings)
    findings2 = review_board(board, single_focus=False)
    assert not any("multiple tickets in DOING" in m for _s, _i, m in findings2)


def test_blocked_without_reason_warned():
    board = build_board("BLOCKED S-001 A")
    findings = review_board(board)
    assert any("without a blocked-by" in m for _s, _i, m in findings)


def test_done_still_needed_is_info():
    board = build_board("DONE S-001 A", "TODO S-002 B")
    board.get("S-002").set_field("needs", "S-001")
    findings = review_board(board)
    assert any(f[0] == "info" and "still needed" in f[2] for f in findings)


def test_no_completion_criterion_is_info_not_warn():
    board = build_board("TODO S-001 Fix the leaky faucet in the kitchen")
    findings = review_board(board)
    infos = [f for f in findings if f[0] == "info"]
    warns = [f for f in findings if f[0] == WARN]
    assert any("done-when" in m for _s, _i, m in infos)
    assert not any("done-when" in m for _s, _i, m in warns)
