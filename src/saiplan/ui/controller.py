"""BoardController: one writer over BOARD.md, bridging core -> UI.

Qt-free. Every mutation is TRANSACTIONAL:

    current_board -> clone/candidate -> mutate candidate -> render ->
    strict validate -> store.save -> record history/log -> ONLY NOW adopt

The live authoritative in-memory Board is never mutated before persistence
succeeds. A refused save (external edit, validation error) leaves memory,
disk, the undo stacks and the semantic LOG all untouched.

Conflict resolution preserves BOTH sides explicitly (external bytes go to a
conflict copy before the local version is written, and vice versa) — neither
side is ever destroyed.
"""

from __future__ import annotations

from ..core.board import parse_board, parse_board_detailed, render_board, render_ticket
from ..core.config import Config
from ..core.history import History, Trash
from ..core.lifecycle import TransitionRefused, create_ticket, transition
from ..core.logbook import append_event
from ..core.model import BLOCKED, DOING, DONE, TODO, Board, BoardError
from ..core.persistence import (
    BoardStore,
    BoardValidationError,
    CorruptBoardError,
    ExternalEditError,
)
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
        self._readonly = False
        # last committed semantic event, consumed by the UI sound adapter
        self.last_event: str | None = None
        self._load_log()

    # -- loading ------------------------------------------------------
    def _load_log(self) -> None:
        try:
            self.log_text = self.plan.log_path.read_text(encoding="utf-8")
        except OSError:
            self.log_text = ""

    def load(self) -> None:
        """Load BOARD.md.

        - clean valid BOARD -> load (writable)
        - structurally invalid BOARD -> preserve corrupt bytes, restore the
          newest validated snapshot (recover_and_adopt), LOG RECOVERY_USED
        - no valid snapshot -> loud READ-ONLY state; mutations are refused
        - never silently start with a partial parsed board as authority
        """
        text = self.store.load()
        board, errors, warnings = parse_board_detailed(text)
        self._readonly = False
        if errors:
            # primary missing, empty or structurally invalid -> attempt a
            # validated snapshot restore (recover_and_adopt preserves the
            # corrupt bytes first); never keep a partial board as authority
            try:
                text = self.store.recover_and_adopt()
                board, errors2, warnings2 = parse_board_detailed(text)
                warnings = [f"recovered from snapshot: {e}" for e in errors2] + warnings2
                errors = []
                append_event(self.plan.log_path, "RECOVERY_USED", detail=self.plan.board_path.name)
            except CorruptBoardError as e:
                self._readonly = True
                warnings = [f"CORRUPT: {e} — plan is read-only until fixed"]
        self.board = board
        self.warnings = [f"BOARD.md: {e}" for e in errors] + warnings

    @property
    def read_only(self) -> bool:
        return self._readonly

    # -- transactional core --------------------------------------------
    def _clone(self) -> Board:
        text = render_board(self.board)
        board, errors = parse_board(text)
        if errors:
            raise ControllerError("current board cannot be represented; refusing to mutate")
        return board

    def _transaction(
        self, event: str, ticket_id: str | None, detail: str | None, mutator
    ) -> object:
        """One mutation path. Never touches the live board until the save lands."""
        if self._readonly:
            raise ControllerError(
                "plan is read-only (BOARD.md is corrupt and no snapshot exists); mutation refused"
            )
        candidate = self._clone()
        result = mutator(candidate)
        text = render_board(candidate)
        _b, errors, _w = parse_board_detailed(text)
        if errors:
            raise ControllerError(
                f"internal error: mutation produced an invalid board: {errors[0]}"
            )
        prev = self.store.loaded_text or ""
        try:
            self.store.save(text)
        except ExternalEditError:
            raise ControllerError(
                "BOARD.md changed externally; resolve the conflict or reload first"
            )
        except BoardValidationError as e:
            raise ControllerError(str(e))
        # ONLY NOW adopt the candidate
        self.board = candidate
        if ticket_id is None and hasattr(result, "ticket_id"):
            ticket_id = result.ticket_id
        self.history.record(event or "EDIT", prev, text)
        if event:
            append_event(self.plan.log_path, event, ticket_id, detail)
        self.log_text += f" {ticket_id or ''}"
        self.last_event = event
        return result

    # -- mutations -----------------------------------------------------
    def create_ticket(self, title: str, fields=None, status=TODO):
        if not title.strip():
            raise ControllerError("ticket title is empty")

        def mut(board: Board):
            try:
                return create_ticket(
                    board, title, log_text=self.log_text, fields=fields, status=status
                )
            except TransitionRefused as e:
                raise ControllerError(str(e))

        return self._transaction("TICKET_CREATED", None, None, mut)

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

        def mut(board: Board):
            try:
                transition(board, ticket_id, target, reason)
            except TransitionRefused as e:
                raise ControllerError(str(e))
            return board.get(ticket_id)

        event = STATUS_EVENTS.get(target, "TICKET_EDITED")
        return self._transaction(event, ticket_id, reason, mut)

    def edit_field(self, ticket_id: str, key: str, value: str) -> None:
        def mut(board: Board):
            ticket = board.get(ticket_id)
            if ticket is None:
                raise ControllerError(f"{ticket_id} not on the board")
            if key == "title":
                ticket.title = value.strip() or ticket.title
            elif value:
                ticket.set_field(key, value)
            else:
                ticket.remove_field(key)
            return ticket

        self._transaction("TICKET_EDITED", ticket_id, key, mut)

    def delete_ticket(self, ticket_id: str) -> None:
        ticket = self.board.get(ticket_id)
        if ticket is None:
            return
        # trash record first: a later save failure leaves a harmless orphan
        # (duplicate metadata is preferred over a lost ticket)
        Trash(self.plan.history_dir).discard_ticket(
            ticket_id, ticket.title, render_ticket(ticket), self.plan.plan_id
        )

        def mut(board: Board):
            board.remove(ticket_id)

        self._transaction("TICKET_DELETED", ticket_id, None, mut)

    def restore_ticket(self, ticket_id: str) -> None:
        trash = Trash(self.plan.history_dir)
        rec = trash.peek(self.plan.plan_id, ticket_id)
        if rec is None:
            raise ControllerError(f"{ticket_id} not in trash")
        line = rec.get("line", "")
        _b, errors, _w = parse_board_detailed(f"## TODO\n{line}\n## DOING\n## DONE\n## BLOCKED\n")
        if errors or _b.all_tickets() == []:
            raise ControllerError(f"trash record for {ticket_id} is unreadable; not consumed")
        restored = _b.all_tickets()[0]
        restored.remove_field("updated")
        restored.set_field("updated", _now_stamp())

        def mut(board: Board):
            try:
                board.add(restored, status=TODO)
            except BoardError as e:
                raise ControllerError(str(e))
            return restored

        self._transaction("TICKET_RESTORED", ticket_id, None, mut)
        # only after the board persisted do we drop the trash record; a failed
        # cleanup retains the record (duplicate metadata over a lost ticket)
        trash.mark_restored(rec["record_id"])

    # -- undo/redo (transactional) ------------------------------------
    def undo(self) -> bool:
        if self._readonly:
            raise ControllerError("plan is read-only; undo refused")
        if self.has_external_change():
            raise ControllerError(
                "BOARD.md changed externally; undo blocked — resolve the conflict first"
            )
        current = render_board(self.board)
        rec = self.history.peek_undo(current)
        if rec is None:
            return False
        candidate = rec["prev"]
        board, errors, _w = parse_board_detailed(candidate)
        if errors:
            raise ControllerError("undo target is unreadable; history may be corrupt")
        self.store.save(candidate)  # never allow_external for ordinary undo
        self.board = board
        self.warnings = []
        self.history.commit_undo(rec)
        self.last_event = "UNDO"
        return True

    def redo(self) -> bool:
        if self._readonly:
            raise ControllerError("plan is read-only; redo refused")
        if self.has_external_change():
            raise ControllerError(
                "BOARD.md changed externally; redo blocked — resolve the conflict first"
            )
        current = render_board(self.board)
        rec = self.history.peek_redo(current)
        if rec is None:
            return False
        candidate = rec["after"]
        board, errors, _w = parse_board_detailed(candidate)
        if errors:
            raise ControllerError("redo target is unreadable; history may be corrupt")
        self.store.save(candidate)
        self.board = board
        self.warnings = []
        self.history.commit_redo(rec)
        self.last_event = "REDO"
        return True

    def can_undo(self) -> bool:
        return self.history.can_undo()

    def can_redo(self) -> bool:
        return self.history.can_redo()

    # -- external edits / conflicts ------------------------------------
    def has_external_change(self) -> bool:
        return self.store.has_external_change()

    def external_text(self) -> str | None:
        """Current on-disk bytes (the side that caused the conflict)."""
        try:
            return self.board_path.read_text(encoding="utf-8")
        except OSError:
            return None

    @property
    def board_path(self):
        return self.plan.board_path

    def _conflict_target(self, side: str) -> object:
        import time

        from ..core.persistence import atomic_write

        target = self.plan.directory / (
            f"BOARD.conflict-{side}-{time.strftime('%Y%m%d-%H%M%S')}.md"
        )
        return target, atomic_write

    def resolve_keep_mine(self) -> str | None:
        """Keep the LOCAL version as canonical. The EXTERNAL version is
        written to BOARD.conflict-external-<ts>.md first; only after that copy
        is verified does the local version overwrite the canonical file.
        Never destroys either side."""
        local = render_board(self.board)
        external = self.external_text()
        copy_path = None
        if external is not None:
            target, atomic_write = self._conflict_target("external")
            try:
                atomic_write(target, external)
                copy_path = str(target)
            except OSError:
                raise ControllerError("could not write the external conflict copy; nothing changed")
        self.store.save(local, allow_external=True)
        append_event(
            self.plan.log_path,
            "CONFLICT_DETECTED",
            detail=f"kept local; external preserved in {target.name}",
        )
        self.last_event = "CONFLICT_RESOLVED"
        return copy_path

    def resolve_reload_external(self) -> str | None:
        """Adopt the EXTERNAL version as canonical. The LOCAL version is
        written to BOARD.conflict-local-<ts>.md first so nothing is lost."""
        external = self.external_text()
        if external is None:
            return None
        local = render_board(self.board)
        target, atomic_write = self._conflict_target("local")
        try:
            atomic_write(target, local)
        except OSError:
            raise ControllerError("could not write the local conflict copy; nothing changed")
        self.store.load()  # adopt external bytes + refresh guard
        board, errors, warnings = parse_board_detailed(external)
        self.board = board
        self.warnings = [f"BOARD.md: {e}" for e in errors] + warnings
        self._readonly = bool(errors)  # a corrupt external version makes it read-only
        append_event(
            self.plan.log_path,
            "CONFLICT_DETECTED",
            detail=f"reloaded external; local preserved in {target.name}",
        )
        self.last_event = "CONFLICT_RESOLVED"
        return str(target)

    # -- review -------------------------------------------------------
    def review(self):
        single_focus = bool(self.config.get("single_focus", True)) if self.config else True
        return review_board(self.board, single_focus=single_focus)

    # -- structured batch (Break Down) ----------------------------------
    def accept_proposal(self, proposal) -> list:
        """Atomically commit a validated PlanProposal into TODO and update the
        PLAN.md sections. All tasks are validated FIRST; nothing is created
        partially, nothing is silently skipped."""
        from ..core.proposal import apply_proposal, validate_proposal

        problems = validate_proposal(proposal)
        if problems:
            raise ControllerError("proposal is invalid: " + "; ".join(problems[:5]))

        def mut(board: Board):
            return apply_proposal(board, proposal, log_text=self.log_text)

        created = self._transaction("BATCH_CREATED", None, None, mut)
        # BOARD (authority) already persisted; now update the descriptive doc
        try:
            self.plan.update_plan_doc(
                objective=proposal.goal,
                constraints=proposal.constraints,
                definition_of_done=proposal.definition_of_done,
            )
        except OSError:
            pass  # a stale PLAN.md must not undo the committed tickets
        return created


def _now_stamp() -> str:
    import datetime

    return datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
