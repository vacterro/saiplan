"""AI boundary (spec 16): prepared interfaces, no provider soup.

Core accepts a structured PlanProposal; provider adapters (future:
local/external LLM) produce it; SAIPLAN validates the structure; a human
accepts it; tickets then enter TODO through the normal controller path.
AI never owns persistence — apply_proposal only mutates an in-memory Board.

No OpenAI/Anthropic/Gemini-specific assumptions exist anywhere in core.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .lifecycle import create_ticket
from .model import PRIORITY_ORDER, Board, Ticket

PRIORITIES = tuple(PRIORITY_ORDER.keys())


@dataclass
class TaskProposal:
    title: str
    needs: list[str] = field(default_factory=list)  # titles of other tasks
    priority: str = "normal"
    done_when: str = ""
    due: str = ""


@dataclass
class PlanProposal:
    goal: str
    constraints: str = ""
    definition_of_done: str = ""
    tasks: list[TaskProposal] = field(default_factory=list)
    provider: str = ""  # adapter identity, informational only


def _task_titles(proposal: PlanProposal) -> list[str]:
    return [t.title.strip() for t in proposal.tasks]


def validate_proposal(proposal: PlanProposal) -> list[str]:
    """Structural validation. Empty list == acceptable plan.

    Checks: goal present, at least one task, non-empty titles, unique titles
    (they are the `needs:` keys), valid priority, `needs:` only referencing
    existing task titles, no dependency cycles. Nothing consults a provider.
    """
    problems: list[str] = []
    if not isinstance(proposal, PlanProposal):
        return ["proposal is not a PlanProposal"]
    if not (proposal.goal or "").strip():
        problems.append("goal is empty")
    if not proposal.tasks:
        problems.append("proposal has no tasks")
        return problems

    titles = _task_titles(proposal)
    for i, title in enumerate(titles):
        if not title:
            problems.append(f"task {i} has an empty title")
    seen = set()
    for title in titles:
        if title and title in seen:
            problems.append(f"duplicate task title {title!r}; needs references become ambiguous")
        seen.add(title)
    for i, task in enumerate(proposal.tasks):
        if task.priority not in PRIORITIES:
            problems.append(f"task {i} has unknown priority {task.priority!r}")
        for need in task.needs or []:
            if not isinstance(need, str) or need not in titles:
                problems.append(f"task {i} needs {need!r} which is not a task in the proposal")

    # cycle detection over titles
    by_title = {t: p for t, p in zip(titles, proposal.tasks)}
    visited: set[str] = set()
    active: set[str] = set()

    def walk(title: str) -> bool:
        if title in active:
            return True
        if title in visited:
            return False
        active.add(title)
        for need in by_title[title].needs or []:
            if need in by_title and walk(need):
                return True
        active.discard(title)
        visited.add(title)
        return False

    for title in by_title:
        if walk(title):
            problems.append("dependency cycle in proposal")
            break
    return problems


def apply_proposal(board: Board, proposal: PlanProposal, *, log_text: str = "") -> list[Ticket]:
    """Create the proposal's tickets on `board` in TODO (I2).

    Only called AFTER a human accepts. Task titles map to real S-ids; the
    `needs:` field on the board line uses those S-ids. Persistence stays with
    the caller (controller), never here.
    """
    if validate_proposal(proposal):
        raise ValueError("cannot apply an invalid PlanProposal; fix structure first")
    title_to_id: dict[str, str] = {}
    created: list[Ticket] = []
    for task in proposal.tasks:
        fields = []
        if task.done_when:
            fields.append(("done-when", task.done_when))
        if task.due:
            fields.append(("due", task.due))
        if task.priority and task.priority != "normal":
            fields.append(("priority", task.priority))
        ticket = create_ticket(
            board, task.title.strip(), log_text=log_text, fields=fields, status="TODO"
        )
        title_to_id[task.title.strip()] = ticket.ticket_id
        created.append(ticket)
    for task, ticket in zip(proposal.tasks, created):
        ids = [title_to_id[t] for t in (task.needs or []) if t in title_to_id]
        if ids:
            ticket.set_field("needs", ",".join(ids))
    return created
