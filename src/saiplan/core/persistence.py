"""Persistence: atomic write, external-edit detection, backup rotation.

Adapted from the audited writers:
- FastPrompter `portable_backup._write_raw` + SAIPEN `codec.write_document`
  (temp + flush + fsync + os.replace)
- SAIPENVIEW `textio.write_doc` (unique temp name, mode preservation)
- SAIPENVIEW SelfWriteRegistry / ExternalChangeRegistry (causal attribution)

Data-safety contract (spec 9 / I4 / I5): a corrupt or empty new state never
replaces a healthy backup; an external edit is never silently overwritten.
"""

from __future__ import annotations

import hashlib
import os
import stat
import tempfile
import time
from pathlib import Path

_TS = "sha256"


class ExternalEditError(RuntimeError):
    """The canonical file changed on disk since we loaded it. Caller must
    reload, merge, or write an explicit conflict copy — never silently save."""


class CorruptBoardError(RuntimeError):
    """The board file is unreadable and no valid backup exists."""


def file_fingerprint(path: Path) -> str:
    """Typed identity: `MISSING` for an absent file, else sha256\\0mtime_ns.

    A missing file never equals an empty file (SAIPENVIEW rule)."""
    try:
        raw = path.read_bytes()
    except OSError:
        return "MISSING"
    return f"{_TS}\\0{hashlib.sha256(raw).hexdigest()}\\0{path.stat().st_mtime_ns}"


def _probe_writable(path: Path) -> bool:
    try:
        fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".wprobe-")
        os.close(fd)
        os.remove(tmp)
        return True
    except OSError:
        return False


def atomic_write(path: Path, text: str, *, encoding: str = "utf-8", newline: str = "\n") -> None:
    """Write `text` atomically. Raises on failure; target untouched on error."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not _probe_writable(path):
        raise OSError(f"directory is not writable: {path.parent}")
    if newline != "\n":
        text = text.replace("\n", newline)
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=path.name + ".tmp-")
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(text.encode(encoding, errors="replace"))
            fh.flush()
            os.fsync(fh.fileno())
        if path.exists():
            try:
                os.chmod(tmp, stat.S_IMODE(path.stat().st_mode))
            except OSError:
                pass
        os.replace(tmp, path)
    except BaseException:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise


def _text_is_valid(text: str) -> bool:
    """A trustworthy board: non-empty and parses cleanly (or still yields
    tickets). Empty text is never trusted as a recovery snapshot."""
    if not text or not text.strip():
        return False
    from .board import parse_board

    _board, errors = parse_board(text)
    return not errors or any(_board.all_tickets())


def validate_snapshot(path: Path, minimum_non_empty: int = 1) -> bool:
    """A snapshot is trustworthy only if it exists, is non-empty and parses."""
    try:
        raw = path.read_bytes()
    except OSError:
        return False
    if len(raw) < minimum_non_empty:
        return False
    return _text_is_valid(raw.decode("utf-8", errors="replace"))


class BoardStore:
    """Owns one BOARD.md: loads it, guards it against external edits, saves it
    safely with rotating snapshots + optional one-way mirror."""

    def __init__(
        self,
        board_path: Path,
        history_dir: Path,
        mirror_dir: Path | None = None,
        snapshot_keep: int = 14,
        mirror: bool = False,
    ):
        self.board_path = Path(board_path)
        self.history_dir = Path(history_dir)
        self.mirror_dir = Path(mirror_dir) if mirror_dir and mirror else None
        self.snapshot_keep = max(1, int(snapshot_keep))
        self.guard = "MISSING"
        self.loaded_text: str | None = None

    # -- load ---------------------------------------------------------
    def load(self) -> str:
        """Read BOARD.md. Returns text. External edits are never overwritten
        afterwards because the guard records the loaded bytes."""
        try:
            self.loaded_text = self.board_path.read_text(encoding="utf-8")
        except OSError:
            self.loaded_text = ""
        self.guard = file_fingerprint(self.board_path)
        return self.loaded_text

    def has_external_change(self) -> bool:
        return file_fingerprint(self.board_path) != self.guard

    # -- save ---------------------------------------------------------
    def save(self, text: str, *, allow_external: bool = False, force: bool = False) -> None:
        """Persist new board state. Refuses (ExternalEditError) when the file
        changed externally unless explicitly allowed or bytes are identical."""
        if not force and not allow_external and self.has_external_change():
            raise ExternalEditError(
                "BOARD.md changed outside SAIPLAN since it was loaded; "
                "reload or create a conflict copy instead of overwriting"
            )
        previous = self.board_path.read_bytes() if self.board_path.exists() else b""
        atomic_write(self.board_path, text)
        self.loaded_text = text
        self._after_save(previous)
        self.guard = file_fingerprint(self.board_path)

    def _after_save(self, previous: bytes) -> None:
        # Snapshot the NEW state only when it is healthy: an empty or corrupt
        # save must never rotate itself into the backup chain on top of a good
        # one (spec 9). Recovery then always has the last trustworthy board.
        new_text = self.loaded_text or ""
        if _text_is_valid(new_text):
            snap = self.history_dir / (
                f"snapshot-{time.strftime('%Y%m%d-%H%M%S')}-"
                f"{int(time.time() * 1000) % 1000000:06d}-"
                f"{os.urandom(2).hex()}.board.md"
            )
            try:
                atomic_write(snap, new_text)
            except OSError:
                pass
            self._prune(self.history_dir, "snapshot-*.board.md", self.snapshot_keep)
        # 2. one-way mirror: write-only copy, never delete, never read back
        if self.mirror_dir is not None:
            try:
                atomic_write(self.mirror_dir / "BOARD.md", new_text)
            except OSError:
                pass  # mirror failure must not fail the save (spec 9)

    def _validated_previous(self, previous: bytes) -> bool:
        return bool(previous) and _text_is_valid(previous.decode("utf-8", errors="replace"))

    @staticmethod
    def _prune(directory: Path, pattern: str, keep: int) -> None:
        snaps = BoardStore._snapshots(directory)
        for old in snaps[:-keep]:
            try:
                old.unlink()
            except OSError:
                pass

    @staticmethod
    def _snapshots(directory: Path) -> list[Path]:
        """All snapshot paths, oldest first. Sorted by mtime so same-second
        saves (identical filename timestamps) still recover newest-first."""
        try:
            snaps = list(directory.glob("snapshot-*.board.md"))
        except OSError:
            return []
        snaps.sort(key=lambda p: (p.stat().st_mtime_ns, p.name))
        return snaps

    # -- recovery -----------------------------------------------------
    def latest_snapshot(self) -> Path | None:
        snaps = self._snapshots(self.history_dir)
        return snaps[-1] if snaps else None

    def recover(self) -> str:
        """Load latest VALIDATED snapshot text, or raise CorruptBoardError."""
        snaps = self._snapshots(self.history_dir)
        if not snaps:
            raise CorruptBoardError("BOARD.md is corrupt and no snapshot exists")
        for candidate in reversed(snaps):
            try:
                text = candidate.read_text(encoding="utf-8")
            except OSError:
                continue
            if validate_snapshot(candidate):
                return text
        raise CorruptBoardError("BOARD.md is corrupt and no valid snapshot exists")
