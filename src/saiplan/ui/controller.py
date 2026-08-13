"""BoardController: one writer over BOARD.md, bridging core -> UI.

Qt-free. The UI calls methods, the controller mutates the in-memory Board,
persists through BoardStore (atomic + guarded), records undo/redo, writes
semantic LOG events and (optionally) trashes deleted tickets. All UI refreshes
happen after each call — the controller never pushes events itself.
"""

from __future__ import annotations

from ..core.board import parse_board, render_board
from ..core.config import Config
from ..core.history import History
from ..core.lifecycle import TransitionRefused, create_ticket, transition
from ..core.logbook import append_event
from ..core.model import BLOCKED, DOING, DONE, TODO, Board
from ..core.persistence import BoardStore, CorruptBoardError, ExternalEditError
from ..core.plan import Plan
from ..core.review import review_board

STATUS_EVENTS = {
    DOING: "TICKET_STARTED",
    DONE: "TICKET_DONE",
    BLOCKED: "TICKET_BLOCKED",
    TODO: "TICKET_REOPENED",
}


class ControllerError(Exception):
    pass


class BoardController:
    def __init__(self, plan: Plan, store: BoardStore, config: Config | None = None):
        self.plan = plan
        self.store = store
        self.config = config
        self.history = History(plan.undo_dir)
        self.board = Board()
        self.log_text = ""
        self.warnings: list[str] = []
        self._load_log()

    # -- loading ------------------------------------------------------
    def _load_log(self) -> None:
        try:
            self.log_text = self.plan.log_path.read_text(encoding="utf-8")
        except OSError:
            self.log_text = ""

    def load(self) -> None:
        """Load BOARD.md; on structural corruption fall back to a validated
        snapshot and LOG RECOVERY_USED. Never silently start empty."""
        try:
            text = self.store.load()
        except OSError:
            text = ""
        board, errors = parse_board(text)
        self.warnings = [f"BOARD.md: {e}" for e in errors]
        if board.all_tickets() == [] and errors and self.plan.board_path.exists():
            # primary is unreadable or structurally dead -> recover
            try:
                text = self.store.recover()
                board, errors = parse_board(text)
                self.warnings = [f"recovered from snapshot: {e}" for e in errors]
                append_event(self.plan.log_path, "RECOVERY_USED", detail=self.plan.board_path.name)
            except CorruptBoardError as e:
                self.warnings = [f"CORRUPT: {e}"]
        self.board = board

    # -- writes -------------------------------------------------------
    def _commit(self, event: str, ticket_id: str | None = None, detail: str | None = None) -> None:
        prev = self.store.loaded_text or ""
        text = render_board(self.board)
        try:
            self.store.save(text)
        except ExternalEditError:
            # the UI shows the conflict banner; the in-memory board is newer
            # than disk and must not be silently discarded
            raise ControllerError("BOARD.md changed externally; reload or keep a conflict copy")
        self.history.record(event or "EDIT", prev, text)
        if event:
            append_event(self.plan.log_path, event, ticket_id, detail)
        self.log_text += f" {ticket_id or ''}"

    def create_ticket(self, title: str, fields=None, status=TODO):
        if not title.strip():
            raise ControllerError("ticket title is empty")
        try:
            ticket = create_ticket(
                self.board, title, log_text=self.log_text, fields=fields, status=status
            )
        except TransitionRefused as e:
            raise ControllerError(str(e))
        self._commit("TICKET_CREATED", ticket.ticket_id)
        return ticket

    def transition(self, ticket_id: str, target: str, reason: str | None = None):
        if target == BLOCKED and not (reason or "").strip():
            raise ControllerError("blocking requires a reason")
        if (
            target == TODO
            and self.board.get(ticket_id)
            and self.board.get(ticket_id).status == BLOCKED
            and not (reason or "").strip()
        ):
            raise ControllerError("unblocking requires the decision")
        try:
            transition(self.board, ticket_id, target, reason)
        except TransitionRefused as e:
            raise ControllerError(str(e))
        event = STATUS_EVENTS.get(target, "TICKET_EDITED")
        self._commit(event, ticket_id, reason)

    def edit_field(self, ticket_id: str, key: str, value: str) -> None:
        ticket = self.board.get(ticket_id)
        if ticket is None:
            raise ControllerError(f"{ticket_id} not on the board")
        if key in ("title",):
            ticket.title = value.strip() or ticket.title
        elif value:
            ticket.set_field(key, value)
        else:
            ticket.remove_field(key)
        self._commit("TICKET_EDITED", ticket_id, f"{key}")

    def delete_ticket(self, ticket_id: str) -> None:
        ticket = self.board.get(ticket_id)
        if ticket is None:
            return
        from ..core.board import render_ticket
        from ..core.history import Trash

        Trash(self.plan.trash_path.parent).discard_ticket(
            ticket_id, ticket.title, render_ticket(ticket), self.plan.plan_id
        )
        self.board.remove(ticket_id)
        self._commit("TICKET_DELETED", ticket_id)

    def restore_ticket(self, ticket_id: str) -> None:
        from ..core.history import Trash

        rec = Trash(self.plan.trash_path.parent).restore(self.plan.plan_id, ticket_id)
        if rec is None:
            raise ControllerError(f"{ticket_id} not in trash")
        line = rec.get("line", "")
        _board, errors = parse_board(f"## TODO\n{line}\n## DOING\n## DONE\n## BLOCKED\n")
        if errors or _board.all_tickets() == []:
            raise ControllerError("trash record for {ticket_id} is unreadable")
        restored = _board.all_tickets()[0]
        restored.remove_field("updated")
        restored.set_field("updated", _now_stamp())
        self.board.add(restored, status=TODO)
        self._commit("TICKET_RESTORED", ticket_id)

    # -- undo/redo ----------------------------------------------------
    def undo(self) -> bool:
        current = render_board(self.board)
        prev = self.history.undo(current)
        if prev is None:
            return False
        self._apply_external(prev)
        return True

    def redo(self) -> bool:
        current = render_board(self.board)
        after = self.history.redo(current)
        if after is None:
            return False
        self._apply_external(after)
        return True

    def can_undo(self) -> bool:
        return self.history.can_undo()

    def can_redo(self) -> bool:
        return self.history.can_redo()

    def _apply_external(self, text: str) -> None:
        """Apply an undo/redo snapshot, forcing the store to match."""
        board, errors = parse_board(text)
        self.board = board
        self.warnings = [f"BOARD.md: {e}" for e in errors]
        self.store.save(text, allow_external=True)

    # -- external edits -----------------------------------------------
    def has_external_change(self) -> bool:
        return self.store.has_external_change()

    def reload_from_disk(self) -> bool:
        """Reload BOARD.md, adopting the on-disk (external) version."""
        try:
            text = self.store.load()
        except OSError:
            return False
        board, errors = parse_board(text)
        self.board = board
        self.warnings = [f"BOARD.md: {e}" for e in errors]
        append_event(self.plan.log_path, "CONFLICT_DETECTED", detail="reloaded external version")
        return True

    def make_conflict_copy(self) -> str | None:
        """Write BOARD.conflict-<ts>.md with the in-memory state. Returns the
        copy path, or None on failure."""
        import time

        from ..core.persistence import atomic_write

        text = render_board(self.board)
        target = self.plan.directory / f"BOARD.conflict-{time.strftime('%Y%m%d-%H%M%S')}.md"
        try:
            atomic_write(target, text)
        except OSError:
            return None
        append_event(
            self.plan.log_path, "CONFLICT_DETECTED", detail=f"saved conflict copy {target.name}"
        )
        return str(target)

    # -- review -------------------------------------------------------
    def review(self):
        single_focus = bool(self.config.get("single_focus", True)) if self.config else True
        return review_board(self.board, single_focus=single_focus)


def _now_stamp() -> str:
    import datetime

    return datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
