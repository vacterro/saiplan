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
import time
import uuid
from pathlib import Path

from .persistence import atomic_write

UNDO_CAP = 200

_REQUIRED_KEYS = ("prev", "after")


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

    # -- low level ----------------------------------------------------
    @staticmethod
    def _read_lines(path: Path) -> list[dict]:
        """Valid records only; malformed lines and records missing required
        keys are skipped (never a KeyError, never a crash)."""
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
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

    @staticmethod
    def _truncate(path: Path, keep: int) -> None:
        lines = History._read_lines(path)
        if len(lines) > keep:
            _atomic_write_lines(path, lines[-keep:])

    def record(self, op: str, prev_text: str, after_text: str) -> None:
        rec = {
            "seq": int(time.time() * 1000),
            "op": op,
            "ts": _now(),
            "prev": prev_text,
            "after": after_text,
        }
        self._append(self.undo_path, rec)
        self._truncate(self.undo_path, UNDO_CAP)
        # a new mutation invalidates the redo stack
        try:
            self.redo_path.unlink()
        except OSError:
            pass

    # -- transactional stack ops --------------------------------------
    def _top_matching(self, path: Path, current_text: str, key: str) -> dict | None:
        """Newest record whose `key` differs from current_text (so applying it
        changes the board). Inspects without moving the stack."""
        records = self._read_lines(path)
        for rec in reversed(records):
            if rec.get(key) != current_text:
                return rec
        return None

    def peek_undo(self, current_text: str) -> dict | None:
        return self._top_matching(self.undo_path, current_text, "prev")

    def peek_redo(self, current_text: str) -> dict | None:
        return self._top_matching(self.redo_path, current_text, "after")

    def commit_undo(self, rec: dict) -> None:
        """Move the top undo record to the redo stack (after the candidate
        board was already persisted successfully). `rec` is the record that
        peek_undo returned — the top of the stack."""
        records = self._read_lines(self.undo_path)
        if not records:
            return
        rest = records[:-1]
        _atomic_write_lines(self.undo_path, rest)
        self._append(self.redo_path, rec)

    def commit_redo(self, rec: dict) -> None:
        """Move the top redo record back to the undo stack."""
        records = self._read_lines(self.redo_path)
        if not records:
            return
        rest = records[:-1]
        _atomic_write_lines(self.redo_path, rest)
        self._append(self.undo_path, rec)
        self._truncate(self.undo_path, UNDO_CAP)

    def can_undo(self) -> bool:
        return bool(self._read_lines(self.undo_path))

    def can_redo(self) -> bool:
        return bool(self._read_lines(self.redo_path))


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
        return rec["record_id"]

    def _all(self) -> list[dict]:
        out = []
        try:
            lines = self.path.read_text(encoding="utf-8").splitlines()
        except OSError:
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
