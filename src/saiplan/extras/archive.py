"""Archive closed plans (extras). Moving a plan directory out of `plans/`
into `data/archive/` keeps the working list small while nothing is lost.

Identity is NEVER reconstructed from a display filename. Every archive writes
`archive.json` with the original immutable `plan_id`; restore returns the plan
to EXACTLY that id (a deterministic suffix only when a collision exists).
"""

from __future__ import annotations

import datetime
import json
import os
import re
import shutil
import uuid
from datetime import UTC
from pathlib import Path

from ..core.board import parse_board_detailed, validate_board_semantics
from ..core.persistence import atomic_write
from ..core.plan import PlanError, read_plan_md, validate_plan_id

ARCHIVE_META = "archive.json"
_DATE_SUFFIX = re.compile(r"-\d{4}-\d{2}-\d{2}(?:-\d+)?$")


def archive_root(plans_dir: Path) -> Path:
    return plans_dir.parent / "archive"


def archive_plan(plans_dir: Path, plan_id: str) -> Path | None:
    """Move a plan dir to data/archive/<plan_id>-<date>/ with archive.json."""
    src = plans_dir / plan_id
    if not src.is_dir():
        return None
    root = archive_root(plans_dir)
    root.mkdir(parents=True, exist_ok=True)
    stamp = datetime.datetime.now(UTC).date().isoformat()
    dst = root / f"{plan_id}-{stamp}"
    n = 1
    while dst.exists():
        n += 1
        dst = root / f"{plan_id}-{stamp}-{n}"
    staging = root / f".archiving-{uuid.uuid4().hex}"
    try:
        atomic_write(
            src / ARCHIVE_META,
            json.dumps({"original_plan_id": plan_id, "archived_at": stamp}, indent=2),
        )
        shutil.move(str(src), str(staging))
        os.replace(staging, dst)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        return None
    return dst


def _original_plan_id(archived: Path) -> str | None:
    meta = archived / ARCHIVE_META
    if meta.exists():
        try:
            data = json.loads(meta.read_text(encoding="utf-8"))
            original = data.get("original_plan_id") if isinstance(data, dict) else None
            if (
                isinstance(original, str)
                and original not in ("", ".", "..")
                and Path(original).name == original
            ):
                return original
        except (json.JSONDecodeError, OSError, TypeError, UnicodeError):
            return None
        return None
    # legacy archive (pre-metadata): strip a trailing `-YYYY-MM-DD[-N]`
    return _DATE_SUFFIX.sub("", archived.name) or archived.name


def list_archived(plans_dir: Path) -> list[Path]:
    root = archive_root(plans_dir)
    if not root.is_dir():
        return []
    return sorted(d for d in root.iterdir() if d.is_dir())


def restore_plan(plans_dir: Path, archived: Path) -> Path | None:
    """Move an archived plan back into plans/ under its ORIGINAL immutable
    plan_id. A collision gets a deterministic `-restored` suffix."""
    if not archived.is_dir():
        return None
    try:
        info = read_plan_md(archived / "PLAN.md")
        board_text = (archived / "BOARD.md").read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return None
    board, errors, _warnings = parse_board_detailed(board_text)
    if not info["name"] or errors or validate_board_semantics(board):
        return None
    original = _original_plan_id(archived)
    if not original:
        return None
    try:
        validate_plan_id(original)
    except PlanError:
        return None
    dst = plans_dir / original
    suffix = 0
    while dst.exists():
        suffix += 1
        ending = "-restored" if suffix == 1 else f"-restored-{suffix}"
        dst = plans_dir / f"{original}{ending}"
    staging = plans_dir / f".creating-{uuid.uuid4().hex}"
    try:
        shutil.move(str(archived), str(staging))
        os.replace(staging, dst)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        return None
    try:
        (dst / ARCHIVE_META).unlink()
    except OSError:
        pass
    return dst
