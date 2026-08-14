"""Persisted undo/redo + trash (spec 9, spec 19).

FastPrompter's undo is in-memory only (audited). SAIPLAN persists it: every
mutation records the previous and next BOARD text into `.history/undo.jsonl`,
so undo/redo survive a restart. Trash records deleted tickets/attachments in
`.history/trash.jsonl`; nothing is ever permanently destroyed by the UI
(Delete always trashes).

History is TRANSACTIONAL: peek_undo/peek_redo inspect the top of a stack
without moving it; commit_undo/commit_redo move a record only AFTER the
controller has successfully persisted the candidate board. A failed save
therefore leaves both stacks byte-identical. All stack rewrites use the
atomic writer. Corrupt JSON lines and records missing required fields are
skipped, never raised.
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

from .persistence import atomic_write, process_file_lock

UNDO_CAP = 200

_REQUIRED_KEYS = ("prev", "after")
_ISSUED_ID = re.compile(r"(?<![A-Za-z0-9_-])([ST])-(\d+)(?![A-Za-z0-9_-])")


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _atomic_write_lines(path: Path, records: list[dict]) -> None:
    body = "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records)
    atomic_write(path, body)


class History:
    def __init__(self, directory: Path):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.undo_path = self.directory / "undo.jsonl"
        self.redo_path = self.directory / "redo.jsonl"
        self._lock = threading.RLock()
        self._migrate_stacks()

    # -- low level ----------------------------------------------------
    @staticmethod
    def _read_lines(path: Path) -> list[dict]:
        """Valid records only; malformed lines and records missing required
        keys are skipped (never a KeyError, never a crash)."""
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeError):
            return []
        out = []
        for line in lines:
            if not line.strip():
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(rec, dict) or not all(k in rec for k in _REQUIRED_KEYS):
                continue
            if not isinstance(rec["prev"], str) or not isinstance(rec["after"], str):
                continue
            out.append(rec)
        return out

    @staticmethod
    def _append(path: Path, record: dict) -> None:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
            fh.flush()
            os.fsync(fh.fileno())

    @staticmethod
    def _truncate(path: Path, keep: int) -> None:
        lines = History._read_lines(path)
        if len(lines) > keep:
            _atomic_write_lines(path, lines[-keep:])

    def record(self, op: str, prev_text: str, after_text: str) -> None:
        if prev_text == after_text:
            return
        rec = {
            "record_id": uuid.uuid4().hex,
            "seq": int(time.time() * 1000),
            "op": op,
            "ts": _now(),
            "prev": prev_text,
            "after": after_text,
        }
        with self._lock:
            self._append(self.undo_path, rec)
            self._truncate(self.undo_path, UNDO_CAP)
            # a new mutation invalidates the redo stack
            try:
                self.redo_path.unlink()
            except OSError:
                pass

    # -- transactional stack ops --------------------------------------
    def _migrate_stacks(self) -> None:
        """Drop legacy no-ops and give legacy records immutable identities."""
        for path in (self.undo_path, self.redo_path):
            records = self._read_lines(path)
            migrated = []
            changed = False
            seen_ids: set[str] = set()
            for rec in records:
                if rec["prev"] == rec["after"]:
                    changed = True
                    continue
                record_id = rec.get("record_id")
                if not isinstance(record_id, str) or not record_id or record_id in seen_ids:
                    rec = {**rec, "record_id": uuid.uuid4().hex}
                    changed = True
                seen_ids.add(rec["record_id"])
                migrated.append(rec)
            if changed:
                _atomic_write_lines(path, migrated)

    @staticmethod
    def _top_matching(path: Path, current_text: str, current_key: str, target_key: str):
        """Return only an applicable physical stack top."""
        records = History._read_lines(path)
        if not records:
            return None
        rec = records[-1]
        if rec[current_key] != current_text or rec[target_key] == current_text:
            return None
        return rec

    def peek_undo(self, current_text: str) -> dict | None:
        return self._top_matching(self.undo_path, current_text, "after", "prev")

    def peek_redo(self, current_text: str) -> dict | None:
        return self._top_matching(self.redo_path, current_text, "prev", "after")

    def commit_undo(self, record_id: str) -> None:
        """Move the top undo record to the redo stack (after the candidate
        board was already persisted successfully). `rec` is the record that
        peek_undo returned — the top of the stack."""
        records = self._read_lines(self.undo_path)
        if not records or records[-1].get("record_id") != record_id:
            raise RuntimeError("undo stack changed after peek")
        rec = records[-1]
        rest = records[:-1]
        redo = self._read_lines(self.redo_path)
        if not any(item.get("record_id") == record_id for item in redo):
            self._append(self.redo_path, rec)
        _atomic_write_lines(self.undo_path, rest)

    def commit_redo(self, record_id: str) -> None:
        """Move the top redo record back to the undo stack."""
        records = self._read_lines(self.redo_path)
        if not records or records[-1].get("record_id") != record_id:
            raise RuntimeError("redo stack changed after peek")
        rec = records[-1]
        rest = records[:-1]
        undo = self._read_lines(self.undo_path)
        if not any(item.get("record_id") == record_id for item in undo):
            self._append(self.undo_path, rec)
        _atomic_write_lines(self.redo_path, rest)
        self._truncate(self.undo_path, UNDO_CAP)

    def can_undo(self) -> bool:
        return bool(self._read_lines(self.undo_path))

    def can_redo(self) -> bool:
        return bool(self._read_lines(self.redo_path))

    @contextmanager
    def locked(self):
        """Serialize peek, authority save, and exact stack commit."""
        with self._lock:
            yield


class IdSequence:
    """Durable per-plan issuance watermark, independent from visible tickets."""

    def __init__(self, history_dir: Path, board_path: Path, log_path: Path):
        self.history_dir = Path(history_dir)
        self.history_dir.mkdir(parents=True, exist_ok=True)
        self.path = self.history_dir / "id-sequence.json"
        self.board_path = Path(board_path)
        self.log_path = Path(log_path)
        self._lock = threading.Lock()
        self.lock_path = self.history_dir / ".writer.lock"

    @staticmethod
    def _scan_text(text: str, maxima: dict[str, int]) -> None:
        for prefix, number in _ISSUED_ID.findall(text):
            try:
                parsed = int(number)
            except ValueError:
                continue
            maxima[prefix] = max(maxima[prefix], parsed)

    def _evidence_maxima(self) -> dict[str, int]:
        maxima = {"S": 0, "T": 0}
        paths = [
            self.board_path,
            self.log_path,
            self.history_dir / "trash.jsonl",
            self.history_dir / "undo.jsonl",
            self.history_dir / "redo.jsonl",
        ]
        for path in paths:
            try:
                self._scan_text(path.read_text(encoding="utf-8"), maxima)
            except (OSError, UnicodeError):
                continue
        return maxima

    def _load(self) -> dict[str, int]:
        maxima = self._evidence_maxima()
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            raw = {}
        if isinstance(raw, dict):
            for prefix in maxima:
                value = raw.get(prefix)
                if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                    maxima[prefix] = max(maxima[prefix], value)
        atomic_write(self.path, json.dumps(maxima, ensure_ascii=False, indent=2) + "\n")
        return maxima

    def reserve(self, count: int = 1, prefix: str = "S") -> list[str]:
        if prefix not in ("S", "T") or not isinstance(count, int) or count < 1:
            raise ValueError("invalid ticket ID reservation")
        with self._lock, process_file_lock(self.lock_path):
            maxima = self._load()
            first = maxima[prefix] + 1
            maxima[prefix] += count
            atomic_write(self.path, json.dumps(maxima, ensure_ascii=False, indent=2) + "\n")
            return [f"{prefix}-{number}" for number in range(first, maxima[prefix] + 1)]


class Trash:
    """Deleted tickets/attachments, recoverable by default (I6).

    Every record carries an immutable unique `record_id` — identity is never
    a timestamp (two deletes in the same second stay independent). Restoring
    is a two-phase peek/mark: the controller only marks a record restored
    AFTER the candidate board was persisted, so a failed restore keeps the
    trash copy.
    """

    def __init__(self, directory: Path):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.path = self.directory / "trash.jsonl"

    def discard_ticket(self, ticket_id: str, title: str, render_line: str, plan: str) -> str:
        rec = {
            "kind": "ticket",
            "record_id": uuid.uuid4().hex,
            "ts": _now(),
            "plan": plan,
            "ticket_id": ticket_id,
            "title": title,
            "line": render_line,
        }
        with open(self.path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
            fh.flush()
            os.fsync(fh.fileno())
        return rec["record_id"]

    def _all(self) -> list[dict]:
        out = []
        try:
            lines = self.path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeError):
            return out
        for line in lines:
            if not line.strip():
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(rec, dict) and rec.get("kind") == "ticket":
                out.append(rec)
        return out

    def list(self, plan: str | None = None) -> list[dict]:
        return [r for r in self._all() if plan is None or r.get("plan") == plan]

    def peek(self, plan: str, ticket_id: str) -> dict | None:
        """Newest matching record, WITHOUT removing it."""
        recs = [r for r in self.list(plan) if r.get("ticket_id") == ticket_id]
        return recs[-1] if recs else None

    def mark_restored(self, record_id: str) -> bool:
        """Remove exactly the record with this record_id. Returns False when
        the record is already gone (duplicate metadata is retained, never
        silently dropped)."""
        kept = [r for r in self._all() if r.get("record_id") != record_id]
        if len(kept) == len(self._all()):
            return False
        _atomic_write_lines(self.path, kept)
        return True
