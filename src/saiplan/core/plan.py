"""Plan directory management: create/open/list plans, PLAN.md lifecycle.

Portable: everything under one data root (`data/plans/`). Moving the whole
app folder moves everything (I14).

PLAN.md is a small structured document with a surgical model: the known
sections (`Objective`, `Constraints`, `Definition of Done`) plus the
title/created lines are editable; ANY other section a human wrote is
preserved verbatim (never destroyed by a rename/update).

Plan identity is an immutable `plan_id` (`<slug>-<short-id>`); the human
name lives in PLAN.md and may be any Unicode. Rename never changes identity.
"""

from __future__ import annotations

import datetime
import os
import re
import uuid
from dataclasses import dataclass, field
from datetime import UTC
from pathlib import Path

from .logbook import append_event
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

KNOWN_SECTIONS = ("Objective", "Constraints", "Definition of Done")


class PlanError(ValueError):
    pass


def slugify(name: str) -> str:
    """Filesystem-safe slug component of the plan_id. The human name itself
    stays Unicode in PLAN.md; the slug only needs to be unique-ish."""
    name = (name or "").strip().lower()
    base = _INVALID_CHARS.sub("", name).strip().replace(" ", "-").strip("-_.")
    if not base:
        base = "plan"
    if base.split(".")[0] in _WIN_DEVICES:
        base = "plan-" + base
    return base


def new_plan_id(name: str) -> str:
    """Immutable plan identity: `<slug>-<short-id>`. Collision-free by
    construction (uuid), never derived from the human name alone — two
    different multilingual names never collapse onto one id."""
    suffix = uuid.uuid4().hex[:6]
    return f"{slugify(name)}-{suffix}"


@dataclass
class PlanDoc:
    """Structured PLAN.md model. `other` preserves every block the writer does
    not own (unknown headings, free text) so a human edit never gets eaten."""

    name: str = ""
    created: str = ""
    sections: dict[str, str] = field(default_factory=lambda: {s: "" for s in KNOWN_SECTIONS})
    other: list[str] = field(default_factory=list)  # preserved raw blocks

    def render(self) -> str:
        out = []
        title_seen = created_seen = False
        for block in self.other:
            if block.startswith("# ") and not title_seen:
                out.append(f"# {self.name}" if self.name else block)
                title_seen = True
                continue
            if block.startswith("created:") and not created_seen:
                out.append(f"created: {self.created}" if self.created else block)
                created_seen = True
                continue
            out.append(block)
        if not title_seen and self.name:
            out.append(f"# {self.name}")
        if not created_seen and self.created:
            out.append(f"created: {self.created}")
        if out and out[-1].strip():
            out.append("")
        # known sections, in canonical order, then any unknown sections kept
        written = set()
        body = []
        for section in KNOWN_SECTIONS:
            body.append(f"## {section}")
            if self.sections.get(section):
                body.append(self.sections[section].strip())
            body.append("")
            written.add(section)
        # unknown sections live in self.other; emit them after known ones
        return "\n".join(out + body).rstrip() + "\n"


def _split_blocks(text: str) -> list[str]:
    """Group raw text into blocks by top-level heading boundaries."""
    lines = text.splitlines()
    blocks: list[str] = []
    current: list[str] = []
    for line in lines:
        if line.startswith(("# ", "## ")) and current:
            blocks.append("\n".join(current).rstrip())
            current = []
        current.append(line)
    if current:
        blocks.append("\n".join(current).rstrip())
    return [b for b in blocks if b]


def read_plan_doc(path: Path) -> PlanDoc:
    doc = PlanDoc()
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return doc
    blocks = _split_blocks(text)
    for block in blocks:
        lines = block.splitlines()
        first = lines[0].strip() if lines else ""
        if first.startswith("# ") and not doc.name:
            doc.name = first[2:].strip()
            continue
        if first.startswith("created:") and not doc.created:
            doc.created = first[8:].strip()
            continue
        if first.startswith("## "):
            heading = first[3:].strip()
            body = "\n".join(lines[1:]).strip()
            if heading in KNOWN_SECTIONS:
                doc.sections[heading] = body
                continue
        doc.other.append(block)
    return doc


def write_plan_doc(path: Path, doc: PlanDoc) -> None:
    atomic_write(path, doc.render())


def read_plan_md(path: Path) -> dict:
    """Backward-compatible reader -> {name, objective, created, constraints,
    definition_of_done, raw_doc}."""
    doc = read_plan_doc(path)
    return {
        "name": doc.name,
        "objective": doc.sections.get("Objective", ""),
        "created": doc.created,
        "constraints": doc.sections.get("Constraints", ""),
        "definition_of_done": doc.sections.get("Definition of Done", ""),
        "doc": doc,
    }


class Plan:
    def __init__(
        self,
        plan_id: str,
        directory: Path,
        name: str,
        objective: str = "",
        created: str = "",
        constraints: str = "",
        definition_of_done: str = "",
    ):
        self.plan_id = plan_id
        self.directory = directory
        self.name = name
        self.objective = objective
        self.created = created
        self.constraints = constraints
        self.definition_of_done = definition_of_done

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

    def update_plan_doc(self, **fields) -> None:
        """Surgically update known PLAN.md fields, preserving everything else."""
        doc = read_plan_doc(self.plan_md_path)
        if "name" in fields:
            doc.name = fields["name"]
        if "objective" in fields:
            doc.sections["Objective"] = fields["objective"]
        if "constraints" in fields:
            doc.sections["Constraints"] = fields["constraints"]
        if "definition_of_done" in fields:
            doc.sections["Definition of Done"] = fields["definition_of_done"]
        if not doc.created:
            doc.created = datetime.datetime.now(UTC).date().isoformat()
        write_plan_doc(self.plan_md_path, doc)
        self.name = doc.name
        self.objective = doc.sections["Objective"]
        self.constraints = doc.sections["Constraints"]
        self.definition_of_done = doc.sections["Definition of Done"]


class PlanStore:
    def __init__(self, plans_dir: Path):
        self.plans_dir = Path(plans_dir)
        self.plans_dir.mkdir(parents=True, exist_ok=True)

    def list_plans(self) -> list[Plan]:
        out = []
        for entry in sorted(self.plans_dir.iterdir()):
            if entry.name.startswith(".creating-"):
                continue  # staging dirs are never plans
            if entry.is_dir() and entry.joinpath("PLAN.md").exists():
                info = read_plan_md(entry / "PLAN.md")
                if info["name"]:
                    out.append(self._from_info(entry, info))
        return out

    def get(self, plan_id: str) -> Plan | None:
        d = self.plans_dir / plan_id
        if not d.is_dir() or not (d / "PLAN.md").exists():
            return None
        info = read_plan_md(d / "PLAN.md")
        return self._from_info(d, info) if info["name"] else None

    @staticmethod
    def _from_info(directory: Path, info: dict) -> Plan:
        return Plan(
            directory.name,
            directory,
            info["name"] or directory.name,
            info["objective"],
            info["created"],
            info["constraints"],
            info["definition_of_done"],
        )

    def create(
        self,
        name: str,
        objective: str = "",
        constraints: str = "",
        definition_of_done: str = "",
    ) -> Plan:
        """Create a plan TRANSACTIONALLY: stage everything under
        `plans/.creating-<uuid>/`, then atomically rename into place. A crash
        mid-build leaves only an ignored staging dir, never a partial plan."""
        name = (name or "Plan").strip()
        plan_id = new_plan_id(name)
        created = datetime.datetime.now(UTC).date().isoformat()

        staging = self.plans_dir / f".creating-{uuid.uuid4().hex}"
        try:
            for sub in ("notes", "attachments", ".history"):
                (staging / sub).mkdir(parents=True, exist_ok=True)
            plan = Plan(plan_id, staging, name, objective, created, constraints, definition_of_done)
            atomic_write(staging / "PLAN.md", _render_plan_md(plan))
            atomic_write(staging / "BOARD.md", "## DOING\n## TODO\n## DONE\n## BLOCKED\n")
            atomic_write(staging / "LOG.md", "# LOG\n")
            final = self.plans_dir / plan_id
            os.replace(staging, final)  # atomic, same filesystem
        except OSError:
            import shutil

            shutil.rmtree(staging, ignore_errors=True)
            raise
        plan.directory = final
        append_event(final / "LOG.md", "PLAN_CREATED", detail=f"plan '{name}'")
        return plan


def _render_plan_md(plan: Plan) -> str:
    parts = [f"# {plan.name}", "", f"created: {plan.created}", ""]
    for section, value in (
        ("Objective", plan.objective),
        ("Constraints", plan.constraints),
        ("Definition of Done", plan.definition_of_done),
    ):
        parts.append(f"## {section}")
        if value:
            parts.append(value)
        parts.append("")
    return "\n".join(parts).rstrip() + "\n"
