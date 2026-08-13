"""AI boundary (spec 16): PlanProposal in, TODO tickets out, human in the
middle. Core has zero provider assumptions; persistence stays with the
controller, never with the proposal path."""

import pytest

from saiplan.core.model import Board
from saiplan.core.proposal import PlanProposal, TaskProposal, apply_proposal, validate_proposal


def _good():
    return PlanProposal(
        goal="Install a new SSD",
        constraints="must fit a 2280 M.2 slot",
        definition_of_done="system boots from the new drive",
        tasks=[
            TaskProposal("Buy and install new SSD"),
            TaskProposal("Research compatible models", needs=["Buy and install new SSD"]),
            TaskProposal("Clone the old drive", needs=["Buy and install new SSD"], priority="high"),
            TaskProposal("Verify boot", needs=["Clone the old drive"], done_when="boot completes"),
        ],
        provider="test-adapter",
    )


def test_valid_proposal_passes_validation():
    assert validate_proposal(_good()) == []


def test_applies_into_todo_with_real_ids():
    board = Board()
    tickets = apply_proposal(board, _good())
    assert len(tickets) == 4
    assert all(t.status == "TODO" for t in board.all_tickets())
    assert board.counts()["TODO"] == 4
    # proposal needs map to real S-ids on the board
    research = board.get("S-2")
    assert research.get("needs") == "S-1"
    boot = board.get("S-4")
    assert boot.get("needs") == "S-3"
    assert boot.get("done-when") == "boot completes"
    high = board.get("S-3")
    assert high.get("priority") == "high"


def test_malformed_proposals_rejected():
    assert validate_proposal(None) != []
    assert validate_proposal(PlanProposal(goal="", tasks=[TaskProposal("x")])) != []
    assert validate_proposal(PlanProposal(goal="g")) != []  # no tasks
    assert validate_proposal(PlanProposal(goal="g", tasks=[TaskProposal("")])) != []
    assert (
        validate_proposal(PlanProposal(goal="g", tasks=[TaskProposal("x", priority="warp")])) != []
    )


def test_duplicate_titles_rejected():
    p = PlanProposal(goal="g", tasks=[TaskProposal("same"), TaskProposal("same", needs=["same"])])
    assert any("duplicate task title" in m for m in validate_proposal(p))


def test_dangling_needs_rejected():
    p = PlanProposal(goal="g", tasks=[TaskProposal("a"), TaskProposal("b", needs=["no such task"])])
    problems = validate_proposal(p)
    assert any("no such task" in m for m in problems)


def test_cycle_rejected():
    p = PlanProposal(
        goal="g", tasks=[TaskProposal("a", needs=["b"]), TaskProposal("b", needs=["a"])]
    )
    assert any("cycle" in m for m in validate_proposal(p))


def test_apply_refuses_invalid():
    with pytest.raises(ValueError):
        apply_proposal(Board(), PlanProposal(goal="g"))


def test_apply_does_not_persist():
    """apply_proposal touches only the in-memory board — no files."""
    import inspect

    from saiplan.core import proposal

    source = inspect.getsource(proposal)
    for forbidden in ("open(", "write_text", "Path(", "json.dump"):
        assert forbidden not in source


def test_no_provider_soup_in_core():
    """Core must not import any provider SDK (only words in a docstring
    are fine; imports are not)."""
    import inspect

    from saiplan.core import proposal

    source = inspect.getsource(proposal).lower()
    for forbidden in (
        "import openai",
        "import anthropic",
        "import gemini",
        "from openai",
        "import requests",
        "import httpx",
    ):
        assert forbidden not in source
