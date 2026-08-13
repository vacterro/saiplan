"""Archive closed plans (extras). Moving a plan directory out of `plans/`
into `data/archive/` keeps the working list small while nothing is lost.

Identity is NEVER reconstructed from a display filename. Every archive writes
`archive.json` with the original immutable `plan_id`; restore returns the plan
to EXACTLY that id (a deterministic suffix only when a collision exists).
"""

from __future__ import annotations

import datetime
import json
import re
import shutil
from datetime import UTC
from pathlib import Path

from ..core.persistence import atomic_write

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
    shutil.move(str(src), str(dst))
    try:
        atomic_write(
            dst / ARCHIVE_META,
            json.dumps({"original_plan_id": plan_id, "archived_at": stamp}, indent=2),
        )
    except OSError:
        pass  # missing metadata degrades to the filename heuristic on restore
    return dst


def _original_plan_id(archived: Path) -> str:
    meta = archived / ARCHIVE_META
    if meta.exists():
        try:
            data = json.loads(meta.read_text(encoding="utf-8"))
            if isinstance(data.get("original_plan_id"), str) and data["original_plan_id"]:
                return data["original_plan_id"]
        except (json.JSONDecodeError, OSError):
            pass
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
    original = _original_plan_id(archived)
    dst = plans_dir / original
    if dst.exists():
        dst = plans_dir / f"{original}-restored"
    shutil.move(str(archived), str(dst))
    return dst
