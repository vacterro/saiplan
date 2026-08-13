"""Debounced in-memory search over a board (spec 20: event-driven, no busy
loops).

Truth: this indexes the BOARD only. Plan notes are searched separately by
`extras.notes.note_search`; the two are not merged in v0.1.x.
"""

from __future__ import annotations

from .model import Board


class Searcher:
    """Tiny inverted index, rebuilt only on explicit refresh. A board this
    size does not need Lucene; it needs debounce (spec 20)."""

    def __init__(self):
        self._index: list[dict] = []

    def refresh(self, board: Board) -> None:
        self._index = []
        for _s, t in board:
            text = f"{t.ticket_id} {t.title}"
            for k, v in t.fields:
                text += f" {k} {v}"
            self._index.append({"id": t.ticket_id, "text": text.lower()})

    def search(self, query: str) -> list[dict]:
        q = (query or "").strip().lower()
        if not q:
            return [{"id": r["id"]} for r in self._index]
        terms = [t for t in q.split() if t]
        out = []
        for r in self._index:
            if all(term in r["text"] for term in terms):
                out.append({"id": r["id"]})
        return out
