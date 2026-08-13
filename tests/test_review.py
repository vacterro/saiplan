"""Plan Review advisory checks (spec 5): warn, never block. Low-noise:
waiting on a legitimate open prerequisite is normal and never warned."""

from conftest import build_board

from saiplan.core.model import Board
from saiplan.core.review import WARN, review_board


def _messages(findings):
    return [(s, m) for s, _i, m in findings]


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


def test_valid_dependency_chain_does_not_warn():
    """TODO waiting on an open prerequisite is NORMAL — no warning."""
    board = build_board("TODO S-001 Research", "TODO S-002 Buy SSD")
    board.get("S-002").set_field("needs", "S-001")
    findings = review_board(board)
    warns = [m for s, _i, m in findings if s == WARN]
    assert not any("depends" in m or "not DONE" in m for m in warns)


def test_doing_with_unmet_prerequisite_warns():
    board = build_board("DOING S-001 Work", "TODO S-002 Input")
    board.get("S-001").set_field("needs", "S-002")
    findings = review_board(board)
    assert any("is DOING but depends" in m for _s, _i, m in findings)


def test_done_with_unresolved_prerequisite_warns():
    board = build_board("DONE S-001 Done", "TODO S-002 Prereq")
    board.get("S-001").set_field("needs", "S-002")
    findings = review_board(board)
    assert any("prerequisite" in m for _s, _i, m in findings)


def test_done_prerequisite_no_false_positive():
    """A finished prerequisite referenced by a TODO dependent is NORMAL."""
    board = build_board("DONE S-001 Prereq", "TODO S-002 Next")
    board.get("S-002").set_field("needs", "S-001")
    findings = review_board(board)
    assert not any("still needed" in m for _s, _i, m in findings)
    warns = [m for s, _i, m in findings if s == WARN]
    assert not any("S-001" in m for m in warns)


def test_short_title_is_info_not_warn():
    board = build_board("TODO S-001 Buy SSD")
    findings = review_board(board)
    infos = [m for s, _i, m in findings if s == "info"]
    warns = [m for s, _i, m in findings if s == WARN]
    assert any("short title" in m for m in infos)
    assert not any("short title" in m for m in warns)


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


def test_no_completion_criterion_is_info_not_warn():
    board = build_board("TODO S-001 Fix the leaky faucet in the kitchen")
    findings = review_board(board)
    infos = [m for s, _i, m in findings if s == "info"]
    warns = [m for s, _i, m in findings if s == WARN]
    assert any("done-when" in m for m in infos)
    assert not any("done-when" in m for m in warns)
