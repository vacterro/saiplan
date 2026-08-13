"""Plan directory management: create/open/list plans, PLAN.md lifecycle.

Portable: everything under one data root (`data/plans/`). Moving the whole
app folder moves everything (I14).
"""

from __future__ import annotations

import datetime
import hashlib
import re
from datetime import UTC
from pathlib import Path

from .persistence import atomic_write

_INVALID_CHARS = re.compile(r"[^A-Za-z0-9_.\- ]")
_WIN_DEVICES = {
    "con",
    "prn",
    "aux",
    "nul",
    "com1",
    "com2",
    "com3",
    "com4",
    "com5",
    "com6",
    "com7",
    "com8",
    "com9",
    "lpt1",
    "lpt2",
    "lpt3",
    "lpt4",
    "lpt5",
    "lpt6",
    "lpt7",
    "lpt8",
    "lpt9",
}


class PlanError(ValueError):
    pass


def slugify(name: str) -> str:
    """One collision-resistant, filesystem-safe component (FastPrompter
    `fs_component` idea). Two different names never collapse onto one path."""
    name = (name or "").strip().lower()
    base = _INVALID_CHARS.sub("", name).strip().replace(" ", "-").strip("-_.")
    if not base:
        base = "plan"
    if base.split(".")[0] in _WIN_DEVICES:
        base = "plan-" + base
    return base


def _dedupe(plans_dir: Path, base: str) -> str:
    """Append a stable digest when the base slug is already taken."""
    candidate = base
    n = 1
    while (plans_dir / candidate).exists():
        digest = hashlib.sha256(base.encode("utf-8")).hexdigest()[:6]
        candidate = f"{base}-{digest}" if n == 1 else f"{base}-{digest}-{n}"
        n += 1
    return candidate


class Plan:
    def __init__(
        self, plan_id: str, directory: Path, name: str, objective: str = "", created: str = ""
    ):
        self.plan_id = plan_id
        self.directory = directory
        self.name = name
        self.objective = objective
        self.created = created

    @property
    def board_path(self) -> Path:
        return self.directory / "BOARD.md"

    @property
    def log_path(self) -> Path:
        return self.directory / "LOG.md"

    @property
    def plan_md_path(self) -> Path:
        return self.directory / "PLAN.md"

    @property
    def timelog_path(self) -> Path:
        return self.directory / "TIMELOG.jsonl"

    @property
    def notes_dir(self) -> Path:
        return self.directory / "notes"

    @property
    def history_dir(self) -> Path:
        return self.directory / ".history"

    @property
    def trash_path(self) -> Path:
        return self.history_dir / "trash.jsonl"

    @property
    def undo_dir(self) -> Path:
        return self.history_dir

    def ensure_dirs(self) -> None:
        for d in (self.directory, self.notes_dir, self.history_dir, self.directory / "attachments"):
            d.mkdir(parents=True, exist_ok=True)


def read_plan_md(path: Path) -> tuple[str, str, str]:
    """(name, objective, created) from PLAN.md. Tolerant of foreign edits."""
    name, objective, created = "", "", ""
    after = False
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return "", "", ""
    for line in text.splitlines():
        if line.startswith("# ") and not name:
            name = line[2:].strip()
        elif line.startswith("created:"):
            created = line[8:].strip()
        elif line.startswith("## Objective"):
            objective = ""
            after = True
        elif after and line.strip():
            objective = (objective + " " + line.strip()).strip()
    return name, objective, created


class PlanStore:
    def __init__(self, plans_dir: Path):
        self.plans_dir = Path(plans_dir)
        self.plans_dir.mkdir(parents=True, exist_ok=True)

    def list_plans(self) -> list[Plan]:
        out = []
        for entry in sorted(self.plans_dir.iterdir()):
            if entry.is_dir() and entry.joinpath("PLAN.md").exists():
                name, objective, created = read_plan_md(entry / "PLAN.md")
                if name:
                    out.append(Plan(entry.name, entry, name, objective, created))
        return out

    def get(self, plan_id: str) -> Plan | None:
        d = self.plans_dir / plan_id
        if not d.is_dir() or not (d / "PLAN.md").exists():
            return None
        name, objective, created = read_plan_md(d / "PLAN.md")
        return Plan(plan_id, d, name or plan_id, objective, created)

    def create(self, name: str, objective: str = "") -> Plan:
        plan_id = _dedupe(self.plans_dir, slugify(name))
        directory = self.plans_dir / plan_id
        plan = Plan(
            plan_id,
            directory,
            (name or "Plan").strip(),
            objective,
            datetime.datetime.now(UTC).date().isoformat(),
        )
        plan.ensure_dirs()
        atomic_write(plan.plan_md_path, _render_plan_md(plan))
        _write_empty_board(plan.board_path)
        if not plan.log_path.exists():
            atomic_write(plan.log_path, "# LOG\n")
        return plan


def _render_plan_md(plan: Plan) -> str:
    return f"# {plan.name}\n\ncreated: {plan.created}\n\n## Objective\n{plan.objective}\n"


def _write_empty_board(path: Path) -> None:
    atomic_write(path, "## DOING\n## TODO\n## DONE\n## BLOCKED\n")
