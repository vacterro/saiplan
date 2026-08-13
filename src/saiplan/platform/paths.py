"""Portable path resolution (spec 10, I14).

Everything the app needs lives next to the executable:
`SAIPLAN.exe` + `data/` + `themes/` + `sounds/` + `logs/`. Moving or copying
the whole directory moves the complete installation and its data.

If the app directory is read-only the UI must fail loudly or offer an explicit
alternate writable data root — never silently scatter plan data around Windows.
This module reports, the caller decides.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path


def app_root() -> Path:
    """The portable installation root.

    - SAIPLAN_ROOT env var: explicit override (portable deployments, CI)
    - frozen (Nuitka): next to SAIPLAN.exe
    - source tree: three parents above this file (src/saiplan/platform/...)
    """
    forced = os.environ.get("SAIPLAN_ROOT")
    if forced:
        return Path(forced).resolve()
    if getattr(sys, "frozen", False) or getattr(sys, "_MEIPASS", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[3]


def resolve_layout(root: Path | None = None) -> dict[str, Path]:
    root = Path(root) if root else app_root()
    return {
        "root": root,
        "data": root / "data",
        "plans": root / "data" / "plans",
        "config": root / "data" / "config.json",
        "themes": root / "themes",
        "sounds": root / "sounds",
        "logs": root / "logs",
    }


def ensure_layout_dirs(layout: dict[str, Path]) -> None:
    for key in ("data", "plans", "logs"):
        layout[key].mkdir(parents=True, exist_ok=True)


def dir_writable(directory: Path) -> bool:
    try:
        fd, tmp = tempfile.mkstemp(dir=str(directory), prefix=".spw-")
        os.close(fd)
        os.remove(tmp)
        return True
    except OSError:
        return False


def layout_status(layout: dict[str, Path]) -> tuple[bool, str]:
    """(writable_ok, human message). data/ must be writable; themes/sounds
    may be read-only on a locked install but the app stays open."""
    if not layout["data"].exists():
        try:
            layout["data"].mkdir(parents=True)
        except OSError as e:
            return False, f"cannot create data directory: {e}"
    if not dir_writable(layout["data"]):
        return False, (
            f"data directory is not writable: {layout['data']}\n"
            f"Move SAIPLAN to a writable folder or choose a different data "
            f"location. Plan data must never be scattered silently."
        )
    return True, "ok"
