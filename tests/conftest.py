import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


@pytest.fixture
def tmp_plan_dir(tmp_path):
    """A ready plan directory: PLAN.md + empty BOARD.md."""
    from saiplan.core.plan import PlanStore

    store = PlanStore(tmp_path / "plans")
    plan = store.create("Test Plan", "Make things work")
    return plan


def build_board(*rows):
    """Build a Board from compact spec strings `STATUS S-001 Title`.

    Example: build_board("TODO S-001 Buy", "DOING S-002 Build")"""
    from saiplan.core.model import Board

    board = Board()
    for row in rows:
        status, tid, title = row.split(" ", 2)
        from saiplan.core.lifecycle import create_ticket

        create_ticket(board, title, tid=tid, status=status)
    return board
