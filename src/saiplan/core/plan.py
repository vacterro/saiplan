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
from .persistence import BoardStore, atomic_write, validate_snapshot

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
class PlanNode:
    kind: str
    raw: str
    name: str = ""


@dataclass
class PlanDoc:
    """Ordered PLAN.md model; only owned nodes change during updates."""

    name: str = ""
    created: str = ""
    sections: dict[str, str] = field(default_factory=lambda: {s: "" for s in KNOWN_SECTIONS})
    nodes: list[PlanNode] = field(default_factory=list)
    original_name: str = ""
    original_created: str = ""
    original_sections: dict[str, str] = field(default_factory=dict)

    def render(self) -> str:
        out: list[str] = []
        title_seen = created_seen = False
        section_seen: set[str] = set()
        for node in self.nodes:
            ending = "\n" if node.raw.endswith("\n") else ""
            if node.kind == "title" and not title_seen:
                out.append(
                    node.raw if self.name == self.original_name else f"# {self.name}{ending}"
                )
                title_seen = True
            elif node.kind == "created" and not created_seen:
                out.append(
                    node.raw
                    if self.created == self.original_created
                    else f"created: {self.created}{ending}"
                )
                created_seen = True
            elif node.kind == "known_section" and node.name not in section_seen:
                value = self.sections.get(node.name, "")
                if value == self.original_sections.get(node.name, ""):
                    block = node.raw
                else:
                    block = f"## {node.name}\n"
                    if value:
                        block += value
                        if not block.endswith("\n"):
                            block += "\n"
                out.append(block)
                section_seen.add(node.name)
            else:
                out.append(node.raw)
        if not title_seen and self.name:
            out.insert(0, f"# {self.name}\n")
        if not created_seen and self.created:
            insert_at = 1 if out else 0
            out.insert(insert_at, f"\ncreated: {self.created}\n")
        for section in KNOWN_SECTIONS:
            if section not in section_seen:
                if out and not out[-1].endswith("\n\n"):
                    out.append("\n")
                value = self.sections.get(section, "")
                out.append(f"## {section}\n{value + chr(10) if value else ''}")
        rendered = "".join(out)
        return rendered if rendered.endswith("\n") else rendered + "\n"


def read_plan_doc(path: Path) -> PlanDoc:
    doc = PlanDoc()
    try:
        text = path.read_bytes().decode("utf-8")
    except OSError:
        return doc
    lines = text.splitlines(keepends=True)
    first_section = next(
        (index for index, line in enumerate(lines) if line.startswith("## ")), len(lines)
    )
    boundaries = [
        index
        for index, line in enumerate(lines)
        if line.startswith("## ") or (index < first_section and line.startswith(("# ", "created:")))
    ]
    boundaries.append(len(lines))
    cursor = 0
    for position, start in enumerate(boundaries[:-1]):
        if start > cursor:
            doc.nodes.append(PlanNode("raw", "".join(lines[cursor:start])))
        end = boundaries[position + 1]
        line = lines[start]
        if line.startswith("# "):
            doc.name = line[2:].strip()
            doc.nodes.append(PlanNode("title", line))
            cursor = start + 1
            continue
        if line.startswith("created:"):
            doc.created = line[8:].strip()
            doc.nodes.append(PlanNode("created", line))
            cursor = start + 1
            continue
        raw = "".join(lines[start:end])
        heading = line[3:].strip()
        if heading in KNOWN_SECTIONS:
            body = "".join(lines[start + 1 : end]).strip()
            doc.sections[heading] = body
            doc.nodes.append(PlanNode("known_section", raw, heading))
        else:
            doc.nodes.append(PlanNode("unknown_section", raw, heading))
        cursor = end
    if cursor < len(lines):
        doc.nodes.append(PlanNode("raw", "".join(lines[cursor:])))
    doc.original_name = doc.name
    doc.original_created = doc.created
    doc.original_sections = dict(doc.sections)
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
        self.warnings: list[str] = []

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
            initial_board = "## DOING\n## TODO\n## DONE\n## BLOCKED\n"
            atomic_write(staging / "BOARD.md", initial_board)
            board_store = BoardStore(staging / "BOARD.md", staging / ".history")
            board_store.load()
            board_store.save(initial_board)
            snapshots = list((staging / ".history").glob("snapshot-*.board.md"))
            if board_store.last_warnings or not any(validate_snapshot(path) for path in snapshots):
                raise OSError("initial BOARD recovery snapshot could not be created")
            atomic_write(staging / "LOG.md", "# LOG\n")
            final = self.plans_dir / plan_id
            os.replace(staging, final)  # atomic, same filesystem
        except OSError:
            import shutil

            shutil.rmtree(staging, ignore_errors=True)
            raise
        plan.directory = final
        try:
            append_event(final / "LOG.md", "PLAN_CREATED", detail=f"plan '{name}'")
        except OSError as exc:
            plan.warnings.append(f"plan created, but semantic LOG recording failed: {exc}")
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
