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

from dataclasses import dataclass, field
from pathlib import Path

from ..core.attachments import Attachments
from ..core.board import (
    parse_board,
    parse_board_detailed,
    render_board,
    render_ticket,
    validate_board_semantics,
)
from ..core.config import Config
from ..core.history import History, IdSequence, Trash
from ..core.lifecycle import TransitionRefused, create_ticket, transition
from ..core.logbook import append_event
from ..core.model import BLOCKED, DOING, DONE, TODO, Board, BoardError
from ..core.persistence import (
    BoardStore,
    BoardValidationError,
    CorruptBoardError,
    DiskState,
    ExternalEditError,
    validate_snapshot,
)
from ..core.plan import Plan
from ..core.review import review_board


class ControllerError(Exception):
    pass


@dataclass
class MutationResult:
    committed: bool
    warnings: list[str] = field(default_factory=list)
    event: str | None = None
    ticket_id: str | None = None


class BoardController:
    def __init__(self, plan: Plan, store: BoardStore, config: Config | None = None):
        self.plan = plan
        self.store = store
        self.config = config
        self.history = History(plan.undo_dir)
        self.id_sequence = IdSequence(plan.history_dir, plan.board_path, plan.log_path)
        self.board = Board()
        self.log_text = ""
        self.warnings: list[str] = []
        self._readonly = False
        # last committed semantic event, consumed by the UI sound adapter
        self.last_event: str | None = None
        self.last_result = MutationResult(False)
        self._load_log()

    # -- loading ------------------------------------------------------
    def _load_log(self) -> None:
        try:
            self.log_text = self.plan.log_path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            self.log_text = ""

    def load(self) -> None:
        """Load BOARD.md.

        - clean valid BOARD -> load (writable)
        - structurally invalid BOARD -> preserve corrupt bytes, restore the
          newest validated snapshot (recover_and_adopt), LOG RECOVERY_USED
        - no valid snapshot -> loud READ-ONLY state; mutations are refused
        - never silently start with a partial parsed board as authority
        """
        try:
            text = self.store.load()
        except CorruptBoardError:
            text = ""
        board, errors, warnings = parse_board_detailed(text)
        single_focus = bool(self.config.get("single_focus", True)) if self.config else True
        errors.extend(validate_board_semantics(board, single_focus=single_focus))
        self._readonly = False
        if errors:
            # primary missing, empty or structurally invalid -> attempt a
            # validated snapshot restore (recover_and_adopt preserves the
            # corrupt bytes first); never keep a partial board as authority
            try:
                text = self.store.recover_and_adopt()
                board, errors2, warnings2 = parse_board_detailed(text)
                errors2.extend(validate_board_semantics(board, single_focus=single_focus))
                if errors2:
                    raise CorruptBoardError(
                        f"recovery snapshot is semantically invalid: {errors2[0]}"
                    )
                warnings = warnings2
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
        previous_text = render_board(self.board)
        text = render_board(candidate)
        if text == previous_text:
            self.last_event = None
            self.last_result = MutationResult(False, event=None, ticket_id=ticket_id)
            return result
        _b, errors, _w = parse_board_detailed(text)
        if errors:
            raise ControllerError(
                f"internal error: mutation produced an invalid board: {errors[0]}"
            )
        single_focus = bool(self.config.get("single_focus", True)) if self.config else True
        semantic_errors = validate_board_semantics(candidate, single_focus=single_focus)
        if semantic_errors:
            raise ControllerError(semantic_errors[0])
        if ticket_id is None and hasattr(result, "ticket_id"):
            ticket_id = result.ticket_id
        sidecar_warnings: list[str] = []

        def record_sidecars() -> list[str]:
            try:
                self.history.record(event or "EDIT", previous_text, text)
            except Exception as exc:  # noqa: BLE001 - sidecar cannot negate committed BOARD
                sidecar_warnings.append(f"history recording failed: {exc}")
            if event:
                try:
                    append_event(self.plan.log_path, event, ticket_id, detail)
                except Exception as exc:  # noqa: BLE001 - sidecar cannot negate committed BOARD
                    sidecar_warnings.append(f"semantic LOG recording failed: {exc}")
            return sidecar_warnings

        try:
            self.store.save(text, after_commit=record_sidecars)
        except ExternalEditError:
            raise ControllerError(
                "BOARD.md changed externally; resolve the conflict or reload first"
            )
        except BoardValidationError as e:
            raise ControllerError(str(e))
        # ONLY NOW adopt the candidate
        self.board = candidate
        sidecar_warnings = list(self.store.last_warnings)
        self.log_text += f" {ticket_id or ''}"
        self.last_event = event
        self.warnings.extend(sidecar_warnings)
        self.last_result = MutationResult(True, sidecar_warnings, event, ticket_id)
        return result

    # -- mutations -----------------------------------------------------
    def create_ticket(self, title: str, fields=None, status=TODO):
        if not title.strip():
            raise ControllerError("ticket title is empty")

        ticket_id = self.id_sequence.reserve()[0]

        def mut(board: Board):
            try:
                return create_ticket(
                    board,
                    title,
                    tid=ticket_id,
                    log_text=self.log_text,
                    fields=fields,
                    status=status,
                )
            except TransitionRefused as e:
                raise ControllerError(str(e))

        return self._transaction("TICKET_CREATED", None, None, mut)

    def transition(self, ticket_id: str, target: str, reason: str | None = None):
        source = self.board.get(ticket_id).status if self.board.get(ticket_id) else None
        if source == target:
            self.last_event = None
            self.last_result = MutationResult(False)
            return self.board.get(ticket_id)
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
                single_focus = bool(self.config.get("single_focus", True)) if self.config else True
                transition(board, ticket_id, target, reason, single_focus=single_focus)
            except TransitionRefused as e:
                raise ControllerError(str(e))
            return board.get(ticket_id)

        if source == BLOCKED and target == TODO:
            event = "TICKET_UNBLOCKED"
        elif source == DONE and target == TODO:
            event = "TICKET_REOPENED"
        else:
            event = {
                DOING: "TICKET_STARTED",
                DONE: "TICKET_DONE",
                BLOCKED: "TICKET_BLOCKED",
            }.get(target, "TICKET_EDITED")
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

    # -- attachments (sidecar files, not BOARD authority) -------------
    def attach_file(self, ticket_id: str, source, dest_name: str | None = None) -> Path:
        """Copy a file onto a ticket. Sidecar files never touch BOARD.md;
        deleting/reopening the ticket keeps them (I6)."""
        if self.board.get(ticket_id) is None:
            raise ControllerError(f"no such ticket: {ticket_id}")
        return Attachments(self.plan).attach(ticket_id, source, dest_name=dest_name)

    def list_attachments(self, ticket_id: str) -> list[Path]:
        return Attachments(self.plan).list(ticket_id)

    def remove_attachment(self, ticket_id: str, name: str) -> Path:
        """Move one attachment into the plan's attachments trash (byte-exact)."""
        return Attachments(self.plan).remove(ticket_id, name)

    # -- recovery -----------------------------------------------------
    def recovery_artifacts(self) -> list[dict]:
        """Read-only listing for the Recovery UI: rotating snapshots
        (restorable when valid) plus forensic corrupt / restore-before copies
        (view-only evidence). Newest first. Never touches the board."""
        artifacts: list[dict] = []
        for path in self.store.list_snapshots():
            valid = validate_snapshot(path)
            artifacts.append(
                {
                    "kind": "snapshot",
                    "path": str(path),
                    "mtime_ns": path.stat().st_mtime_ns,
                    "valid": valid,
                    "summary": self._artifact_summary(path),
                }
            )
        for path in self.store.list_forensic_copies():
            is_restore = "restore-before" in path.name
            artifacts.append(
                {
                    "kind": "restore-before" if is_restore else "corrupt",
                    "path": str(path),
                    "mtime_ns": path.stat().st_mtime_ns,
                    "valid": False,
                    "summary": self._artifact_summary(path),
                }
            )
        artifacts.sort(key=lambda a: a["mtime_ns"], reverse=True)
        return artifacts

    def _artifact_summary(self, path: Path) -> str:
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return "unreadable"
        board, errors, _w = parse_board_detailed(text)
        if errors:
            return "not a valid board (view only)"
        counts = board.counts()
        return " ".join(f"{k} {counts[k]}" for k in ("DOING", "TODO", "DONE", "BLOCKED"))

    def restore_snapshot(self, snapshot_path) -> MutationResult:
        """Human-initiated restore of a validated snapshot over BOARD.md.

        Safety, in order: refuses a read-only plan, a snapshot that is not a
        strictly valid board, and an externally-changed primary (I5). Then
        preserves the current primary byte-exact to `.history/restore-before-*`
        (I6), records an undo entry (previous_text -> snapshot text), appends
        `SNAPSHOT_RESTORED` to the semantic LOG, and adopts the snapshot only
        AFTER the save lands — a refused save changes nothing.
        """
        if self._readonly:
            raise ControllerError("plan is read-only; restore refused")
        path = Path(snapshot_path)
        if not validate_snapshot(path):
            raise ControllerError("chosen file is not a trustworthy BOARD snapshot")
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise ControllerError(f"snapshot unreadable: {exc}") from exc
        board, errors, _w = parse_board_detailed(text)
        if errors:
            raise ControllerError(f"snapshot is not a valid board: {errors[0]}")
        single_focus = bool(self.config.get("single_focus", True)) if self.config else True
        semantic_errors = validate_board_semantics(board, single_focus=single_focus)
        if semantic_errors:
            raise ControllerError(f"snapshot fails semantic validation: {semantic_errors[0]}")
        previous_text = render_board(self.board)
        if text == previous_text:
            self.last_event = None
            self.last_result = MutationResult(False)
            return self.last_result
        # capture the pre-restore primary bytes NOW; the byte-exact backup is
        # written only after the save lands, so a refused restore leaves no trace
        primary = self.store.read_raw()
        sidecar_warnings: list[str] = []

        if primary.raw:
            try:
                self.store.preserve_before_restore(primary.raw)
            except OSError as exc:
                raise ControllerError(
                    f"restore backup failed; restore refused to protect data: {exc}"
                ) from exc

        def record_sidecars() -> list[str]:
            try:
                self.history.record("SNAPSHOT_RESTORED", previous_text, text)
            except Exception as exc:  # noqa: BLE001 - sidecar cannot negate committed BOARD
                sidecar_warnings.append(f"history recording failed: {exc}")
            try:
                append_event(self.plan.log_path, "SNAPSHOT_RESTORED", detail=path.name)
            except Exception as exc:  # noqa: BLE001 - sidecar cannot negate committed BOARD
                sidecar_warnings.append(f"semantic LOG recording failed: {exc}")
            return sidecar_warnings

        try:
            self.store.save(text, after_commit=record_sidecars)
        except ExternalEditError:
            raise ControllerError(
                "BOARD.md changed externally; resolve the conflict or reload first"
            )
        except BoardValidationError as exc:
            raise ControllerError(str(exc))
        # ONLY NOW adopt the snapshot
        self.board = board
        sidecar_warnings = list(self.store.last_warnings)
        self.warnings.extend(sidecar_warnings)
        self.last_event = "SNAPSHOT_RESTORED"
        self.last_result = MutationResult(True, sidecar_warnings, "SNAPSHOT_RESTORED")
        return self.last_result

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
        with self.history.locked():
            current = render_board(self.board)
            rec = self.history.peek_undo(current)
            if rec is None:
                return False
            candidate = rec["prev"]
            board, errors, _w = parse_board_detailed(candidate)
            single_focus = bool(self.config.get("single_focus", True)) if self.config else True
            errors.extend(validate_board_semantics(board, single_focus=single_focus))
            if errors:
                raise ControllerError("undo target is unreadable; history may be corrupt")
            self.store.save(candidate)  # never allow_external for ordinary undo
            self.board = board
            self.warnings = []
            sidecar_warnings = list(self.store.last_warnings)
            try:
                self.history.commit_undo(rec["record_id"])
            except Exception as exc:  # noqa: BLE001 - sidecar cannot negate committed BOARD
                sidecar_warnings.append(f"undo history commit failed: {exc}")
            self.warnings.extend(sidecar_warnings)
            self.last_result = MutationResult(True, sidecar_warnings, "UNDO")
        self.last_event = "UNDO"
        return True

    def redo(self) -> bool:
        if self._readonly:
            raise ControllerError("plan is read-only; redo refused")
        if self.has_external_change():
            raise ControllerError(
                "BOARD.md changed externally; redo blocked — resolve the conflict first"
            )
        with self.history.locked():
            current = render_board(self.board)
            rec = self.history.peek_redo(current)
            if rec is None:
                return False
            candidate = rec["after"]
            board, errors, _w = parse_board_detailed(candidate)
            single_focus = bool(self.config.get("single_focus", True)) if self.config else True
            errors.extend(validate_board_semantics(board, single_focus=single_focus))
            if errors:
                raise ControllerError("redo target is unreadable; history may be corrupt")
            self.store.save(candidate)
            self.board = board
            self.warnings = []
            sidecar_warnings = list(self.store.last_warnings)
            try:
                self.history.commit_redo(rec["record_id"])
            except Exception as exc:  # noqa: BLE001 - sidecar cannot negate committed BOARD
                sidecar_warnings.append(f"redo history commit failed: {exc}")
            self.warnings.extend(sidecar_warnings)
            self.last_result = MutationResult(True, sidecar_warnings, "REDO")
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
        return self.store.read_raw().text

    @property
    def board_path(self):
        return self.plan.board_path

    def resolve_keep_mine(self) -> str | None:
        """Keep the LOCAL version as canonical. The EXTERNAL version is
        written to BOARD.conflict-external-<ts>.md first; only after that copy
        is verified does the local version overwrite the canonical file.
        Never destroys either side."""
        local = render_board(self.board)
        external = self.store.read_raw()
        copy_path = None
        detail: str
        if external.raw is not None:
            try:
                target = self.store.preserve_raw_conflict(external.raw, "external")
                copy_path = str(target)
            except OSError:
                raise ControllerError("could not write the external conflict copy; nothing changed")
            detail = f"kept local; external preserved in {target.name}"
        else:
            detail = "kept local; external BOARD.md was missing"
        try:
            self.store.save(local, expected_guard=external.fingerprint)
        except ExternalEditError as exc:
            raise ControllerError(
                "BOARD.md changed again during conflict resolution; retry"
            ) from exc
        warnings = list(self.store.last_warnings)
        try:
            append_event(self.plan.log_path, "CONFLICT_DETECTED", detail=detail)
        except Exception as exc:  # noqa: BLE001 - sidecar cannot negate committed BOARD
            warnings.append(f"semantic LOG recording failed: {exc}")
        self.warnings.extend(warnings)
        self.last_result = MutationResult(True, warnings, "CONFLICT_RESOLVED")
        self.last_event = "CONFLICT_RESOLVED"
        return copy_path

    def resolve_reload_external(self) -> str | None:
        """Adopt the EXTERNAL version as canonical. The LOCAL version is
        written to BOARD.conflict-local-<ts>.md first so nothing is lost."""
        external = self.store.read_raw()
        local = (
            self.store.loaded_bytes
            if self.store.loaded_bytes is not None
            else render_board(self.board).encode("utf-8")
        )
        try:
            target = self.store.preserve_raw_conflict(local, "local")
        except OSError:
            raise ControllerError("could not write the local conflict copy; nothing changed")
        if self.store.read_raw().fingerprint != external.fingerprint:
            raise ControllerError("BOARD.md changed again during conflict resolution; retry")
        self.store.guard = external.fingerprint
        self.store.loaded_bytes = external.raw
        self.store.loaded_text = external.text
        if external.state == DiskState.MISSING:
            self.board = Board()
            errors = ["external BOARD.md is missing"]
            warnings = []
        elif external.text is None:
            self.board = Board()
            errors = ["external BOARD.md is not valid UTF-8"]
            warnings = []
        else:
            self.board, errors, warnings = parse_board_detailed(external.text)
            single_focus = bool(self.config.get("single_focus", True)) if self.config else True
            errors.extend(validate_board_semantics(self.board, single_focus=single_focus))
        self.warnings = [f"BOARD.md: {e}" for e in errors] + warnings
        self._readonly = bool(errors)
        sidecar_warnings = []
        try:
            append_event(
                self.plan.log_path,
                "CONFLICT_DETECTED",
                detail=f"reloaded external; local preserved in {target.name}",
            )
        except Exception as exc:  # noqa: BLE001 - sidecar cannot negate committed BOARD
            sidecar_warnings.append(f"semantic LOG recording failed: {exc}")
        self.warnings.extend(sidecar_warnings)
        self.last_result = MutationResult(True, sidecar_warnings, "CONFLICT_RESOLVED")
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

        ticket_ids = self.id_sequence.reserve(len(proposal.tasks))

        def mut(board: Board):
            return apply_proposal(board, proposal, log_text=self.log_text, ticket_ids=ticket_ids)

        created = self._transaction("BATCH_CREATED", None, None, mut)
        # BOARD (authority) already persisted; now update the descriptive doc
        try:
            self.plan.update_plan_doc(
                objective=proposal.goal,
                constraints=proposal.constraints,
                definition_of_done=proposal.definition_of_done,
            )
        except (OSError, UnicodeError) as exc:
            warning = f"tickets committed, but PLAN.md update failed: {exc}"
            self.warnings.append(warning)
            self.last_result.warnings.append(warning)
        return created


def _now_stamp() -> str:
    import datetime

    return datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
