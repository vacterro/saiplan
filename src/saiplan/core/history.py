"""Persisted undo/redo + trash (spec 9, spec 19).

FastPrompter's undo is in-memory only (audited). SAIPLAN persists it: every
mutation records the previous and next BOARD text into `.history/undo.jsonl`,
so undo/redo survive a restart. Trash records deleted tickets/attachments in
`.history/trash.jsonl`; nothing is ever permanently destroyed by the UI
(Delete always trashes).
"""

from __future__ import annotations

import json
import time
from pathlib import Path

UNDO_CAP = 200


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


class History:
    def __init__(self, directory: Path):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.undo_path = self.directory / "undo.jsonl"
        self.redo_path = self.directory / "redo.jsonl"

    # -- low level ----------------------------------------------------
    @staticmethod
    def _read_lines(path: Path) -> list[dict]:
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return []
        out = []
        for line in lines:
            if not line.strip():
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return out

    @staticmethod
    def _append(path: Path, record: dict) -> None:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")

    @staticmethod
    def _truncate(path: Path, keep: int) -> None:
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return
        if len(lines) > keep:
            path.write_text("\n".join(lines[-keep:]) + "\n", encoding="utf-8")

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

    def undo(self, current_text: str) -> str | None:
        records = self._read_lines(self.undo_path)
        if not records:
            return None
        rec = records[-1]
        rest = records[:-1]
        self._write_lines(self.undo_path, rest)
        self._append(self.redo_path, rec)
        return rec["prev"] if rec["prev"] != current_text else self.undo(current_text)

    def redo(self, current_text: str) -> str | None:
        records = self._read_lines(self.redo_path)
        if not records:
            return None
        rec = records[-1]
        rest = records[:-1]
        self._write_lines(self.redo_path, rest)
        self._append(self.undo_path, rec)
        return rec["after"] if rec["after"] != current_text else self.redo(current_text)

    def can_undo(self) -> bool:
        return bool(self._read_lines(self.undo_path))

    def can_redo(self) -> bool:
        return bool(self._read_lines(self.redo_path))

    @staticmethod
    def _write_lines(path: Path, records: list[dict]) -> None:
        body = "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records)
        path.write_text(body, encoding="utf-8")


class Trash:
    """Deleted tickets/attachments, recoverable by default (I6)."""

    def __init__(self, directory: Path):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.path = self.directory / "trash.jsonl"

    def discard_ticket(self, ticket_id: str, title: str, render_line: str, plan: str) -> None:
        rec = {
            "kind": "ticket",
            "ts": _now(),
            "plan": plan,
            "ticket_id": ticket_id,
            "title": title,
            "line": render_line,
        }
        with open(self.path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")

    def list(self, plan: str | None = None) -> list[dict]:
        out = []
        try:
            lines = self.path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return out
        for line in lines:
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if rec.get("kind") == "ticket" and (plan is None or rec.get("plan") == plan):
                out.append(rec)
        return out

    def restore(self, plan: str | None, ticket_id: str) -> dict | None:
        """Pop the newest matching record and return it (or None)."""
        records = self.list(plan)
        recs = [r for r in records if r.get("ticket_id") == ticket_id]
        if not recs:
            return None
        rec = recs[-1]
        self._drop_by_ts(rec["ts"])
        return rec

    def _drop_by_ts(self, ts: str) -> None:
        kept = [r for r in self._all() if r.get("ts") != ts]
        body = "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in kept)
        self.path.write_text(body, encoding="utf-8")

    def _all(self) -> list[dict]:
        return self.list()
