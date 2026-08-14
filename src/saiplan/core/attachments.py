"""Ticket attachments (T-029), plain files under the plan folder.

Storage: `data/plans/<plan_id>/attachments/<ticket_id>/<safe-name>`. No extra
manifest — the filesystem IS the record (portable, readable without SAIPLAN).
Ticket identity is immutable and never reused (T-018), so deleting a ticket
never loses its attachments: the folder simply stays and a restored ticket
finds them again.

Safety:

- Filenames keep Unicode but strip path-unsafe characters and Windows device
  names (same discipline as notes). Traversal is impossible by construction:
  only the basename is ever used.
- Collisions get a numeric suffix (`plan-1.pdf`), never overwrite.
- Attach copies the source (the original file is never moved or destroyed).
- Remove moves the file byte-exact to `.history/attachments-trash/<ticket_id>/`
  — nothing is ever permanently deleted (I6).
"""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path

from ..core.persistence import create_new_bytes

_PATH_UNSAFE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_DEVICES = {
    "con",
    "prn",
    "aux",
    "nul",
    *(f"com{i}" for i in range(1, 10)),
    *(f"lpt{i}" for i in range(1, 10)),
}


def safe_attachment_name(name: str) -> str:
    """Unicode-preserving, filesystem-safe attachment filename (basename)."""
    name = unicodedata.normalize("NFC", name or "").strip()
    name = name.replace("\\", "/").split("/")[-1]
    name = _PATH_UNSAFE.sub("_", name)
    name = re.sub(r"\s+", " ", name).strip(" .")
    if not name:
        name = "attachment"
    if name.split(".")[0].lower() in _DEVICES:
        name = f"attachment-{name}"
    if "." in name:
        stem, ext = name.rsplit(".", 1)
        ext = "." + ext
    else:
        stem, ext = name, ""
    if len(name) > 120:
        name = stem[: 120 - len(ext)] + ext
    return name


class Attachments:
    """Owns `attachments/<ticket_id>/` inside one plan folder."""

    def __init__(self, plan) -> None:
        self.plan = plan
        self.directory = plan.directory / "attachments"
        self.trash_dir = plan.history_dir / "attachments-trash"

    # -- listing ------------------------------------------------------
    def list(self, ticket_id: str) -> list[Path]:
        folder = self.directory / ticket_id
        try:
            return sorted(
                (p for p in folder.iterdir() if p.is_file()),
                key=lambda p: p.name.lower(),
            )
        except OSError:
            return []

    def resolve(self, ticket_id: str, name: str) -> Path:
        """Safe path for one attachment; traversal is impossible (basename)."""
        return self.directory / ticket_id / safe_attachment_name(name)

    # -- mutations ----------------------------------------------------
    def attach(self, ticket_id: str, source: Path, dest_name: str | None = None) -> Path:
        """Copy `source` into the ticket's attachment folder. Returns the new
        path. Never overwrites: on collision the name gets a numeric suffix."""
        source = Path(source)
        folder = self.directory / ticket_id
        folder.mkdir(parents=True, exist_ok=True)
        base = safe_attachment_name(dest_name or source.name)
        if "." in base:
            stem, ext = base.rsplit(".", 1)
            ext = "." + ext
        else:
            stem, ext = base, ""

        raw = source.read_bytes()
        counter = 0
        while True:
            suffix = f"-{counter}" if counter > 0 else ""
            target = folder / f"{stem}{suffix}{ext}"
            try:
                create_new_bytes(target, raw)
                break
            except FileExistsError:
                counter += 1
        return target

    def remove(self, ticket_id: str, name: str) -> Path:
        """Move one attachment byte-exact into the plan's attachments trash."""
        path = self.resolve(ticket_id, name)
        if not path.is_file():
            raise FileNotFoundError(f"attachment not found: {path.name}")
        raw = path.read_bytes()
        if "." in path.name:
            stem, ext = path.name.rsplit(".", 1)
            ext = "." + ext
        else:
            stem, ext = path.name, ""
        target = self.trash_dir / ticket_id / path.name
        counter = 1
        while True:
            try:
                create_new_bytes(target, raw)  # refuses to overwrite (O_EXCL)
                break
            except FileExistsError:
                target = self.trash_dir / ticket_id / f"{stem}-{counter}{ext}"
                counter += 1
        path.unlink()
        return target
