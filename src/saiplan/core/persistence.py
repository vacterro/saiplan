"""Persistence: atomic write, external-edit detection, backup rotation.

Adapted from the audited writers:
- FastPrompter `portable_backup._write_raw` + SAIPEN `codec.write_document`
  (temp + flush + fsync + os.replace)
- SAIPENVIEW `textio.write_doc` (unique temp name, mode preservation)
- SAIPENVIEW SelfWriteRegistry / ExternalChangeRegistry (causal attribution)

Data-safety contract (spec 9 / I4 / I5):
- a save is accepted ONLY when the new text is a strictly valid, losslessly
  representable BOARD (empty or corrupt text is rejected, never silently
  canonicalized into BOARD.md);
- an external edit is never silently overwritten;
- a corrupt primary is preserved byte-for-byte before recovery.
"""

from __future__ import annotations

import hashlib
import os
import stat
import tempfile
import time
import uuid
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from .board import board_text_is_strictly_valid, parse_board_detailed, validate_board_semantics

_TS = "sha256"


class ExternalEditError(RuntimeError):
    """The canonical file changed on disk since we loaded it. Caller must
    reload, merge, or write an explicit conflict copy — never silently save."""


class CorruptBoardError(RuntimeError):
    """The board file is unreadable and no valid backup exists."""


class BoardValidationError(ValueError):
    """The caller tried to save text that is not a losslessly representable
    BOARD. The save is refused before any write."""


class DiskState(str, Enum):
    PRESENT_VALID = "PRESENT_VALID"
    PRESENT_INVALID = "PRESENT_INVALID"
    PRESENT_UNDECODABLE = "PRESENT_UNDECODABLE"
    MISSING = "MISSING"


@dataclass(frozen=True)
class RawBoardState:
    state: DiskState
    raw: bytes | None
    text: str | None
    fingerprint: str


def _raw_fingerprint(raw: bytes, mtime_ns: int) -> str:
    return f"{_TS}\\0{hashlib.sha256(raw).hexdigest()}\\0{mtime_ns}"


def _capture_file(path: Path) -> tuple[bytes, str]:
    with open(path, "rb") as fh:
        raw = fh.read()
        mtime_ns = os.fstat(fh.fileno()).st_mtime_ns
    return raw, _raw_fingerprint(raw, mtime_ns)


def file_fingerprint(path: Path) -> str:
    """Typed identity: `MISSING` for an absent file, else sha256\\0mtime_ns.

    A missing file never equals an empty file (SAIPENVIEW rule)."""
    try:
        _raw, fingerprint = _capture_file(path)
    except FileNotFoundError:
        return "MISSING"
    return fingerprint


@contextmanager
def process_file_lock(path: Path):
    """Cross-process advisory lock shared by SAIPLAN authority writers."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a+b") as fh:
        if fh.tell() == 0:
            fh.write(b"\\0")
            fh.flush()
        fh.seek(0)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(fh.fileno(), msvcrt.LK_LOCK, 1)
            try:
                yield
            finally:
                fh.seek(0)
                msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


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
    atomic_write_bytes(path, text.encode(encoding), newline=newline)


def atomic_write_bytes(path: Path, raw: bytes, *, newline: str = "\n") -> None:
    """Write raw bytes atomically (temp + flush + fsync + os.replace)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not _probe_writable(path):
        raise OSError(f"directory is not writable: {path.parent}")
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=path.name + ".tmp-")
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(raw)
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


def _prepared_temp(path: Path, raw: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not _probe_writable(path):
        raise OSError(f"directory is not writable: {path.parent}")
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=path.name + ".tmp-")
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(raw)
            fh.flush()
            os.fsync(fh.fileno())
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    return tmp


def _replace_file_windows(target: Path, replacement: Path, backup: Path) -> None:
    import ctypes

    replace_file = ctypes.windll.kernel32.ReplaceFileW
    replace_file.argtypes = [
        ctypes.c_wchar_p,
        ctypes.c_wchar_p,
        ctypes.c_wchar_p,
        ctypes.c_uint,
        ctypes.c_void_p,
        ctypes.c_void_p,
    ]
    replace_file.restype = ctypes.c_int
    if not replace_file(str(target), str(replacement), str(backup), 1, None, None):
        raise ctypes.WinError()


def conditional_write_bytes(
    path: Path, raw: bytes, expected: str, backup_dir: Path
) -> tuple[bytes | None, list[str]]:
    """Replace only expected authority; return exact previous bytes.

    Windows ReplaceFileW captures previous target atomically. If captured
    identity differs from expected, second atomic replacement restores it.
    """
    path = Path(path)
    replacement = _prepared_temp(path, raw)
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup = backup_dir / f"replace-{uuid.uuid4().hex}.bak"
    rollback = backup_dir / f"rollback-{uuid.uuid4().hex}.bak"
    warnings: list[str] = []
    try:
        current = file_fingerprint(path)
        if current != expected:
            raise ExternalEditError("BOARD.md changed before authority commit")
        if current == "MISSING":
            try:
                os.link(replacement, path)
            except FileExistsError as exc:
                raise ExternalEditError("BOARD.md appeared during authority commit") from exc
            replacement.unlink()
            replacement = None
            return None, warnings
        if os.name == "nt":
            _replace_file_windows(path, replacement, backup)
            replacement = None
            if file_fingerprint(backup) != expected:
                forensic = backup
                try:
                    _replace_file_windows(path, backup, rollback)
                except OSError as exc:
                    backup = None
                    warnings.append(
                        "BOARD.md changed during authority commit; external bytes preserved in "
                        f"{forensic.name}, but rollback failed: {exc}"
                    )
                    return forensic.read_bytes(), warnings
                else:
                    backup = None
                    rollback.unlink(missing_ok=True)
                    raise ExternalEditError("BOARD.md changed during authority commit")
        else:
            os.link(path, backup)
            if file_fingerprint(path) != expected:
                raise ExternalEditError("BOARD.md changed during authority commit")
            os.replace(replacement, path)
            replacement = None
        previous = backup.read_bytes()
        backup.unlink(missing_ok=True)
        return previous, warnings
    finally:
        if replacement is not None:
            replacement.unlink(missing_ok=True)
        if backup is not None:
            backup.unlink(missing_ok=True)
        rollback.unlink(missing_ok=True)


def create_new_bytes(path: Path, raw: bytes) -> None:
    """Create a forensic file exactly once; never replace an existing path."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
    fd = os.open(path, flags, 0o600)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(raw)
            fh.flush()
            os.fsync(fh.fileno())
    except BaseException:
        try:
            path.unlink()
        except OSError:
            pass
        raise


def _text_is_valid(text: str) -> bool:
    """A board is trustworthy ONLY when it is a strictly valid canonical BOARD.
    Any structural error (partial parse) makes it unusable as authority."""
    if not board_text_is_strictly_valid(text):
        return False
    board, errors, _warnings = parse_board_detailed(text)
    return not errors and not validate_board_semantics(board)


def validate_snapshot(path: Path, minimum_non_empty: int = 1) -> bool:
    """A snapshot is trustworthy only if it exists, is non-empty and parses
    with ZERO structural errors."""
    try:
        raw = path.read_bytes()
    except OSError:
        return False
    if len(raw) < minimum_non_empty:
        return False
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return False
    return _text_is_valid(text)


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
        self.loaded_bytes: bytes | None = None
        self.last_warnings: list[str] = []
        self.lock_path = self.history_dir / ".writer.lock"

    # -- load ---------------------------------------------------------
    def load(self) -> str:
        """Read BOARD.md. Returns text. External edits are never overwritten
        afterwards because the guard records the loaded bytes."""
        disk = self.read_raw()
        self.guard = disk.fingerprint
        self.loaded_bytes = disk.raw
        self.loaded_text = disk.text
        if disk.state == DiskState.PRESENT_UNDECODABLE:
            raise CorruptBoardError("BOARD.md is not valid UTF-8")
        return disk.text or ""

    def read_raw(self) -> RawBoardState:
        try:
            raw, fingerprint = _capture_file(self.board_path)
        except FileNotFoundError:
            return RawBoardState(DiskState.MISSING, None, None, "MISSING")
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            return RawBoardState(DiskState.PRESENT_UNDECODABLE, raw, None, fingerprint)
        state = DiskState.PRESENT_VALID if _text_is_valid(text) else DiskState.PRESENT_INVALID
        return RawBoardState(state, raw, text, fingerprint)

    def has_external_change(self) -> bool:
        return file_fingerprint(self.board_path) != self.guard

    # -- save ---------------------------------------------------------
    def save(
        self,
        text: str,
        *,
        allow_external: bool = False,
        force: bool = False,
        expected_guard: str | None = None,
        after_commit: Callable[[], list[str]] | None = None,
    ) -> None:
        """Persist new board state.

        Refuses (BoardValidationError) any text that is not a strictly valid
        BOARD — an empty or partially-parsed board must never be silently
        canonicalized into the authority. Refuses (ExternalEditError) when the
        file changed externally unless explicitly allowed.
        """
        if not force and not _text_is_valid(text):
            raise BoardValidationError("refusing to save a board that cannot be parsed losslessly")
        raw = text.encode("utf-8")
        expected = self.guard if expected_guard is None else expected_guard
        with process_file_lock(self.lock_path):
            if not force and not allow_external and file_fingerprint(self.board_path) != expected:
                raise ExternalEditError(
                    "BOARD.md changed outside SAIPLAN since it was loaded; "
                    "reload or create a conflict copy instead of overwriting"
                )
            if force or allow_external:
                atomic_write_bytes(self.board_path, raw)
                write_warnings = []
            else:
                _previous, write_warnings = conditional_write_bytes(
                    self.board_path, raw, expected, self.history_dir
                )
            self.loaded_bytes = raw
            self.loaded_text = text
            committed = self.read_raw()
            self.guard = committed.fingerprint if committed.raw == raw else "COMMITTED-BUT-CHANGED"
            warnings = write_warnings + self._after_save(raw)
            if after_commit is not None:
                warnings.extend(after_commit())
            self.last_warnings = warnings

    def _after_save(self, raw: bytes) -> list[str]:
        warnings: list[str] = []
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
                atomic_write_bytes(snap, raw)
            except OSError as exc:
                warnings.append(f"snapshot recording failed: {exc}")
            try:
                self._prune(self.history_dir, "snapshot-*.board.md", self.snapshot_keep)
            except OSError as exc:
                warnings.append(f"snapshot pruning failed: {exc}")
        # 2. one-way mirror: write-only copy, never delete, never read back
        if self.mirror_dir is not None:
            try:
                atomic_write_bytes(self.mirror_dir / "BOARD.md", raw)
            except OSError as exc:
                warnings.append(f"mirror update failed: {exc}")
        return warnings

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

    def list_snapshots(self) -> list[Path]:
        """All rotating BOARD snapshots, oldest first (for recovery UI)."""
        return BoardStore._snapshots(self.history_dir)

    def list_forensic_copies(self) -> list[Path]:
        """Byte-exact forensic copies (`corrupt-*` pre-recovery primaries and
        `restore-before-*` pre-restore boards), oldest first. Never pruned:
        recovery evidence is kept on purpose (spec 9)."""
        try:
            copies = []
            for pattern in ("corrupt-*.board.md", "restore-before-*.board.md"):
                copies.extend(self.history_dir.glob(pattern))
        except OSError:
            return []
        copies.sort(key=lambda p: (p.stat().st_mtime_ns, p.name))
        return copies

    # -- recovery -----------------------------------------------------
    def _forensic_target(self, stem: str) -> Path:
        timestamp = time.strftime("%Y%m%d-%H%M%S", time.gmtime())
        return self.history_dir / f"{stem}-{timestamp}-{uuid.uuid4().hex[:8]}.board.md"

    def preserve_before_restore(self, raw: bytes) -> Path:
        """Byte-exact copy of the current primary BEFORE a human-initiated
        snapshot restore lands, so the pre-restore state is never lost (I6).
        Returns the copy path, verified byte-for-byte."""
        target = self._forensic_target("restore-before")
        create_new_bytes(target, raw)
        if target.read_bytes() != raw:
            raise OSError("restore backup copy verification failed")
        return target

    def preserve_raw_corrupt(self, raw: bytes) -> Path:
        target = self._forensic_target("corrupt")
        create_new_bytes(target, raw)
        if target.read_bytes() != raw:
            raise OSError("forensic corrupt copy verification failed")
        return target

    def preserve_raw_conflict(self, raw: bytes, side: str) -> Path:
        timestamp = time.strftime("%Y%m%d-%H%M%S", time.gmtime())
        target = self.board_path.with_name(
            f"BOARD.conflict-{side}-{timestamp}-{uuid.uuid4().hex[:8]}.md"
        )
        create_new_bytes(target, raw)
        if target.read_bytes() != raw:
            raise OSError("forensic conflict copy verification failed")
        return target

    def preserve_corrupt(self) -> Path | None:
        """Copy the current primary bytes to `.history/corrupt-<ts>.board.md`
        BEFORE any recovery overwrites it. Returns the copy path, or None when
        there is nothing to preserve (missing/empty primary)."""
        try:
            raw = self.board_path.read_bytes()
        except OSError:
            return None
        if not raw:
            return None
        return self.preserve_raw_corrupt(raw)

    def recover(self) -> str:
        """Load latest VALIDATED snapshot text, or raise CorruptBoardError."""
        snaps = self._snapshots(self.history_dir)
        if not snaps:
            raise CorruptBoardError("BOARD.md is corrupt and no snapshot exists")
        for candidate in reversed(snaps):
            try:
                raw = candidate.read_bytes()
                text = raw.decode("utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            if raw and _text_is_valid(text):
                return text
        raise CorruptBoardError("BOARD.md is corrupt and no valid snapshot exists")

    def recover_and_adopt(self) -> str:
        """Restore the latest VALIDATED snapshot over the corrupt primary and
        adopt it as the loaded state.

        Order:
        1. preserve the corrupt primary bytes to `.history/corrupt-<ts>.md`
        2. pick the newest valid snapshot (validated, strict)
        3. atomically write it to BOARD.md
        4. set loaded_text + guard to the restored bytes

        After this call, disk / loaded_text / guard describe the SAME state.
        Raises CorruptBoardError when no valid snapshot exists (nothing is
        written in that case — the corrupt primary stays untouched).
        """
        text = self.recover()
        raw = text.encode("utf-8")
        with process_file_lock(self.lock_path):
            primary = self.read_raw()
            if primary.raw:
                try:
                    self.preserve_raw_corrupt(primary.raw)
                except OSError as exc:
                    raise CorruptBoardError(
                        f"could not preserve corrupt BOARD.md; recovery refused: {exc}"
                    ) from exc
            try:
                _previous, write_warnings = conditional_write_bytes(
                    self.board_path, raw, primary.fingerprint, self.history_dir
                )
            except ExternalEditError as exc:
                raise CorruptBoardError("BOARD.md changed during recovery; retry required") from exc
            self.loaded_bytes = raw
            self.loaded_text = text
            committed = self.read_raw()
            self.guard = committed.fingerprint if committed.raw == raw else "COMMITTED-BUT-CHANGED"
            self.last_warnings = write_warnings + self._after_save(raw)
        return text
