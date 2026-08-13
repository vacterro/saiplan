"""Archive closed plans (extras). Moving a plan directory out of `plans/`
into `data/archive/` keeps the working list small while nothing is lost.
Restore moves it back. File-level moves only — archive is not an export.
"""

from __future__ import annotations

import datetime
import shutil
from datetime import UTC
from pathlib import Path


def archive_root(plans_dir: Path) -> Path:
    return plans_dir.parent / "archive"


def archive_plan(plans_dir: Path, plan_id: str) -> Path | None:
    """Move a plan dir to data/archive/<plan_id>-<date>. Returns the new path."""
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
    return dst


def list_archived(plans_dir: Path) -> list[Path]:
    root = archive_root(plans_dir)
    if not root.is_dir():
        return []
    return sorted(d for d in root.iterdir() if d.is_dir())


def restore_plan(plans_dir: Path, archived: Path) -> Path | None:
    """Move an archived plan back into plans/. Returns the plan dir."""
    if not archived.is_dir():
        return None
    dst = plans_dir / archived.name.split("-")[0]
    n = 1
    base = dst
    while dst.exists():
        n += 1
        dst = plans_dir / f"{base.name}-restored-{n}"
    shutil.move(str(archived), str(dst))
    return dst
