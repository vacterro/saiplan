"""Right inspector pane: selected ticket details, fields, checklist, actions.

Collapsible; hidden by default. Editing is autosaved — every field change is
persisted immediately (no Save button in the product's vocabulary).
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path

from PyQt6.QtCore import Qt, QTimer, QUrl, pyqtSignal
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..core.model import BLOCKED, DOING, DONE, TODO, Ticket
from ..core.persistence import atomic_write

SINGLE_LINE_FIELDS = (
    ("due", "due", "Due"),
    ("tags", "tags", "Tags"),
    ("estimate", "estimate", "Estimate"),
    ("needs", "needs", "Needs"),
    ("done-when", "done-when", "Done when"),
)


class Inspector(QWidget):
    board_changed = pyqtSignal()
    save_failed = pyqtSignal(str)

    def __init__(
        self, controller, ticket_timer=None, on_timer_toggle=None, on_notes=None, parent=None
    ):
        super().__init__(parent)
        self.controller = controller
        self.ticket_timer = ticket_timer
        self.on_timer_toggle = on_timer_toggle
        self.on_notes = on_notes
        self.ticket_id: str | None = None
        self._busy = False
        self._dirty_ticket_id: str | None = None
        self._pending_details = ""
        self._revision = 0
        self._failed_values: dict[tuple[str, str, str], str] = {}
        self._skip_retry_once = False
        self._conflict_draft_path = None
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(400)
        self._debounce.timeout.connect(self._save_details)
        self._build()

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(4)

        self.title_edit = QLineEdit()
        self.title_edit.setPlaceholderText("Ticket title")
        self.title_edit.editingFinished.connect(self._save_title)
        layout.addWidget(self.title_edit)

        self.status_label = QLabel()
        self.status_label.setObjectName("sectionTitle")
        layout.addWidget(self.status_label)

        self.timer_row = QHBoxLayout()
        self.timer_button = QPushButton("Start timer")
        self.timer_label = QLabel("")
        self.timer_button.clicked.connect(self._toggle_timer)
        self.timer_row.addWidget(self.timer_button)
        self.timer_row.addWidget(self.timer_label, 1)
        layout.addLayout(self.timer_row)

        form = QFormLayout()
        form.setSpacing(4)
        self.field_edits: dict[str, QLineEdit] = {}
        for key, _attr, label in SINGLE_LINE_FIELDS:
            edit = QLineEdit()
            edit.editingFinished.connect(lambda k=key, e=edit: self._save_field(k, e))
            self.field_edits[key] = edit
            form.addRow(label, edit)
        self.priority_combo = QComboBox()
        self.priority_combo.addItems(["", "low", "normal", "high", "urgent"])
        self.priority_combo.activated.connect(self._save_priority)
        form.addRow("Priority", self.priority_combo)
        layout.addLayout(form)

        details_label = QLabel("Details")
        details_label.setObjectName("sectionTitle")
        layout.addWidget(details_label)
        self.details_edit = QPlainTextEdit()
        self.details_edit.setMaximumHeight(90)
        self.details_edit.textChanged.connect(self._details_changed)
        layout.addWidget(self.details_edit)
        self.unsaved_label = QLabel("")
        self.unsaved_label.setObjectName("warning")
        layout.addWidget(self.unsaved_label)

        checklist_label = QLabel("Checklist")
        checklist_label.setObjectName("sectionTitle")
        layout.addWidget(checklist_label)
        self.checklist = QListWidget()
        self.checklist.setMaximumHeight(120)
        self.checklist.itemClicked.connect(self._toggle_check)
        layout.addWidget(self.checklist, 1)
        row = QHBoxLayout()
        self.check_input = QLineEdit()
        self.check_input.setPlaceholderText("Add checklist item...")
        self.check_input.returnPressed.connect(self._add_check)
        add_btn = QPushButton("Add")
        add_btn.clicked.connect(self._add_check)
        del_btn = QPushButton("Remove")
        del_btn.clicked.connect(self._remove_check)
        row.addWidget(self.check_input, 1)
        row.addWidget(add_btn)
        row.addWidget(del_btn)
        layout.addLayout(row)

        actions = QHBoxLayout()
        self.btn_start = QPushButton("Start")
        self.btn_done = QPushButton("Done")
        self.btn_block = QPushButton("Block")
        self.btn_reopen = QPushButton("Reopen/Unblock")
        self.btn_delete = QPushButton("Delete")
        for b, fn in (
            (self.btn_start, lambda: self._transition(DOING, None)),
            (self.btn_done, lambda: self._transition(DONE, None)),
            (self.btn_block, lambda: self._transition(BLOCKED, True)),
            (self.btn_reopen, lambda: self._transition(TODO, True)),
            (self.btn_delete, self._delete),
        ):
            b.clicked.connect(fn)
            actions.addWidget(b)
        layout.addLayout(actions)

        notes_btn = QPushButton("Notes")
        notes_btn.clicked.connect(self._open_notes)
        layout.addWidget(notes_btn)

        attach_label = QLabel("Attachments")
        attach_label.setObjectName("sectionTitle")
        layout.addWidget(attach_label)
        self.attach_list = QListWidget()
        self.attach_list.setMaximumHeight(100)
        self.attach_list.itemDoubleClicked.connect(lambda _i: self._open_attachment())
        self.attach_list.itemSelectionChanged.connect(self._update_attach_actions)
        layout.addWidget(self.attach_list)
        attach_row = QHBoxLayout()
        self.attach_btn = QPushButton("Attach...")
        self.attach_btn.clicked.connect(self._attach_file)
        self.attach_open_btn = QPushButton("Open")
        self.attach_open_btn.clicked.connect(self._open_attachment)
        self.attach_remove_btn = QPushButton("Remove")
        self.attach_remove_btn.clicked.connect(self._remove_attachment)
        attach_row.addWidget(self.attach_btn)
        attach_row.addWidget(self.attach_open_btn)
        attach_row.addWidget(self.attach_remove_btn)
        layout.addLayout(attach_row)

        layout.addStretch(1)
        self.setMinimumWidth(240)

    # -- display ------------------------------------------------------
    def set_ticket(self, ticket: Ticket | None) -> bool:
        next_id = ticket.ticket_id if ticket else None
        previous_id = self.ticket_id
        if self._skip_retry_once:
            self._skip_retry_once = False
        elif self._dirty_ticket_id and not self.flush_pending():
            return False
        self._busy = True
        self.ticket_id = next_id
        if ticket is None:
            if self._conflict_draft_path is not None:
                preserved_ticket = previous_id
                self.title_edit.setText("")
                self.status_label.setText(
                    f"Ticket removed externally - draft preserved in {self._conflict_draft_path.name}"
                )
                for edit in self.field_edits.values():
                    edit.clear()
                self.priority_combo.setCurrentIndex(0)
                draft = ""
                if preserved_ticket:
                    draft = self._draft(preserved_ticket, "details", "")
                    for key in list(self._failed_values):
                        if key[0] == self._plan_id() and key[1] == preserved_ticket:
                            self._failed_values.pop(key, None)
                self.details_edit.setPlainText(draft)
                self._fill_checklist("")
                self._refresh_attachments()
                self.unsaved_label.setText(f"Draft safely preserved: {self._conflict_draft_path}")
                self._conflict_draft_path = None
                self._busy = False
                return True
            self.title_edit.clear()
            self.status_label.setText("No ticket selected")
            for edit in self.field_edits.values():
                edit.clear()
            self.priority_combo.setCurrentIndex(0)
            self.details_edit.setPlainText("")
            self._fill_checklist("")
            self._refresh_attachments()
            self.timer_button.setEnabled(False)
            for b in (
                self.btn_start,
                self.btn_done,
                self.btn_block,
                self.btn_reopen,
                self.btn_delete,
            ):
                b.setEnabled(False)
            self.timer_label.setText("")
            self._busy = False
            return True
        self.title_edit.setText(self._draft(ticket.ticket_id, "title", ticket.title))
        self.status_label.setText(f"{ticket.ticket_id}  ·  {ticket.status}")
        for key, edit in self.field_edits.items():
            edit.setText(self._draft(ticket.ticket_id, key, ticket.get(key)))
        priority = self._draft(ticket.ticket_id, "priority", ticket.get("priority"))
        idx = self.priority_combo.findText(priority)
        self.priority_combo.setCurrentIndex(max(0, idx))
        self.details_edit.setPlainText(
            self._draft(ticket.ticket_id, "details", ticket.get("details"))
        )
        self._fill_checklist(self._draft(ticket.ticket_id, "checklist", ticket.get("checklist")))
        self._refresh_attachments()
        self.timer_button.setEnabled(True)
        self._refresh_timer_state()
        # enable/disable per status
        status = ticket.status
        self.btn_start.setEnabled(status == TODO)
        self.btn_done.setEnabled(status == DOING)
        self.btn_block.setEnabled(status in (TODO, DOING))
        self.btn_reopen.setEnabled(status in (BLOCKED, DONE))
        self.btn_delete.setEnabled(True)
        self._busy = False
        self._update_unsaved_label()
        return True

    def _fill_checklist(self, raw: str) -> None:
        self.checklist.clear()
        try:
            items = json.loads(raw) if raw else []
        except json.JSONDecodeError:
            items = [i.strip() for i in raw.split(";") if i.strip()]
        for item in items:
            if isinstance(item, dict):
                done = item.get("done", False)
                text = item.get("text", "")
            else:
                done, text = False, str(item)
            li = QListWidgetItem(("☑ " if done else "☐ ") + text)
            li.setData(Qt.ItemDataRole.UserRole, done)
            self.checklist.addItem(li)

    def _refresh_timer_state(self) -> None:
        if self.ticket_timer is None:
            self.timer_button.setEnabled(False)
            return
        running = self.ticket_timer.is_running(self.ticket_id)
        self.timer_button.setText("Stop timer" if running else "Start timer")
        if running:
            self.timer_label.setText(self.ticket_timer.started_at(self.ticket_id) or "")

    # -- saves --------------------------------------------------------
    def _plan_id(self) -> str:
        return self.controller.plan.plan_id if self.controller is not None else ""

    def _draft(self, ticket_id: str, field: str, persisted: str) -> str:
        return self._failed_values.get((self._plan_id(), ticket_id, field), persisted)

    def _mark_failed(self, ticket_id: str, field: str, value: str, error: Exception) -> None:
        self._failed_values[(self._plan_id(), ticket_id, field)] = value
        self._update_unsaved_label()
        self.save_failed.emit(f"Could not save {field}: {error}")

    def _mark_saved(self, ticket_id: str, field: str) -> None:
        self._failed_values.pop((self._plan_id(), ticket_id, field), None)
        self._update_unsaved_label()

    def _update_unsaved_label(self) -> None:
        dirty = bool(self._dirty_ticket_id or self._failed_values)
        self.unsaved_label.setText("Unsaved changes - retry before leaving" if dirty else "")

    def _details_changed(self) -> None:
        if self._busy or not self.ticket_id:
            return
        self._revision += 1
        self._dirty_ticket_id = self.ticket_id
        self._pending_details = self.details_edit.toPlainText()
        self._update_unsaved_label()
        self._debounce.start()

    def flush_pending(self) -> bool:
        if self._dirty_ticket_id:
            self._debounce.stop()
            ticket_id = self._dirty_ticket_id
            pending = self._pending_details
            value = pending.strip().replace("\n", " ")
            try:
                self.controller.edit_field(ticket_id, "details", value)
            except Exception as error:  # noqa: BLE001 - human draft must survive every save failure
                self._mark_failed(ticket_id, "details", pending, error)
                return False
            self._dirty_ticket_id = None
            self._pending_details = ""
            self._mark_saved(ticket_id, "details")
        plan_id = self._plan_id()
        pending_fields = [
            (ticket_id, field, value)
            for (draft_plan, ticket_id, field), value in self._failed_values.items()
            if draft_plan == plan_id
        ]
        for ticket_id, field, value in pending_fields:
            if ticket_id == self.ticket_id:
                if field == "title":
                    value = self.title_edit.text()
                elif field in self.field_edits:
                    value = self.field_edits[field].text()
                elif field == "priority":
                    value = self.priority_combo.currentText()
                elif field == "checklist":
                    value = self._serialize_checklist()
                elif field == "details":
                    value = self.details_edit.toPlainText()
            persisted = value.strip().replace("\n", " ") if field == "details" else value
            try:
                self.controller.edit_field(ticket_id, field, persisted)
            except Exception as error:  # noqa: BLE001 - human draft must survive every save failure
                self.save_failed.emit(f"Could not save {field}: {error}")
                return False
            self._mark_saved(ticket_id, field)
        return True

    def preserve_pending_for_conflict(self) -> bool:
        """Keep visible draft without writing it over chosen conflict authority."""
        if self._dirty_ticket_id:
            self._debounce.stop()
            self._failed_values[(self._plan_id(), self._dirty_ticket_id, "details")] = (
                self._pending_details
            )
            self._dirty_ticket_id = None
            self._pending_details = ""
        plan_id = self._plan_id()
        drafts = {
            f"{ticket_id}:{field}": value
            for (draft_plan, ticket_id, field), value in self._failed_values.items()
            if draft_plan == plan_id
        }
        if drafts:
            target = self.controller.plan.history_dir / (
                f"unsaved-draft-{self.ticket_id}-{uuid.uuid4().hex[:8]}.json"
            )
            try:
                atomic_write(
                    target,
                    json.dumps(
                        {
                            "plan_id": plan_id,
                            "selected_ticket_id": self.ticket_id,
                            "revision": self._revision,
                            "fields": drafts,
                        },
                        ensure_ascii=False,
                        indent=2,
                    )
                    + "\n",
                )
            except OSError as error:
                self.save_failed.emit(
                    f"Could not preserve draft before conflict resolution: {error}"
                )
                return False
            self._conflict_draft_path = target
        self._skip_retry_once = True
        self._update_unsaved_label()
        return True

    def reconcile_after_conflict(self) -> None:
        """Keep surviving drafts; orphan drafts remain in forensic JSON."""
        plan_id = self._plan_id()
        existing = {ticket.ticket_id for ticket in self.controller.board.all_tickets()}
        for key in list(self._failed_values):
            if key[0] == plan_id and key[1] not in existing:
                self._failed_values.pop(key, None)

    def clear_preserved_conflict_draft(self) -> None:
        self._conflict_draft_path = None

    def _save_title(self) -> None:
        if self._busy or not self.ticket_id:
            return
        try:
            self.controller.edit_field(self.ticket_id, "title", self.title_edit.text())
            self._mark_saved(self.ticket_id, "title")
            self.board_changed.emit()
        except Exception as e:  # noqa: BLE001
            self._mark_failed(self.ticket_id, "title", self.title_edit.text(), e)
            QMessageBox.warning(self, "SAIPLAN", str(e))

    def _save_field(self, key: str, edit: QLineEdit) -> None:
        if self._busy or not self.ticket_id:
            return
        try:
            self.controller.edit_field(self.ticket_id, key, edit.text().strip())
            self._mark_saved(self.ticket_id, key)
            self.board_changed.emit()
        except Exception as e:  # noqa: BLE001
            self._mark_failed(self.ticket_id, key, edit.text(), e)
            QMessageBox.warning(self, "SAIPLAN", str(e))

    def _save_priority(self) -> None:
        if self._busy or not self.ticket_id:
            return
        try:
            self.controller.edit_field(
                self.ticket_id, "priority", self.priority_combo.currentText()
            )
            self._mark_saved(self.ticket_id, "priority")
            self.board_changed.emit()
        except Exception as e:  # noqa: BLE001
            self._mark_failed(self.ticket_id, "priority", self.priority_combo.currentText(), e)
            QMessageBox.warning(self, "SAIPLAN", str(e))

    def _save_details(self) -> None:
        if self.flush_pending():
            self.board_changed.emit()

    def _serialize_checklist(self) -> str:
        out = []
        for i in range(self.checklist.count()):
            item = self.checklist.item(i)
            text = item.text()[2:]  # strip ☐/☑ marker
            out.append({"text": text, "done": bool(item.data(Qt.ItemDataRole.UserRole))})
        return json.dumps(out, ensure_ascii=False)

    def _add_check(self) -> None:
        text = self.check_input.text().strip()
        if not text:
            return
        self.checklist.addItem(("☐ ") + text)
        self.check_input.clear()
        self._save_checklist()

    def _remove_check(self) -> None:
        for item in self.checklist.selectedItems():
            self.checklist.takeItem(self.checklist.row(item))
        self._save_checklist()

    def _toggle_check(self, item) -> None:
        item.setData(Qt.ItemDataRole.UserRole, not item.data(Qt.ItemDataRole.UserRole))
        item.setText(("☑ " if item.data(Qt.ItemDataRole.UserRole) else "☐ ") + item.text()[2:])
        self._save_checklist()

    def _save_checklist(self) -> None:
        if not self.ticket_id:
            return
        try:
            self.controller.edit_field(self.ticket_id, "checklist", self._serialize_checklist())
            self._mark_saved(self.ticket_id, "checklist")
            self.board_changed.emit()
        except Exception as e:  # noqa: BLE001
            self._mark_failed(self.ticket_id, "checklist", self._serialize_checklist(), e)

    # -- actions ------------------------------------------------------
    def _transition(self, target: str, needs_reason: bool | None) -> None:
        if not self.ticket_id:
            return
        if not self.flush_pending():
            return
        reason = None
        if needs_reason:
            label = "Why block?" if target == BLOCKED else "What lifts the block / why reopen?"
            reason, ok = QInputDialog.getText(self, "SAIPLAN", label)
            if not ok:
                return
        try:
            self.controller.transition(self.ticket_id, target, reason)
            self.board_changed.emit()  # refresh board columns + status counts
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(self, "SAIPLAN", str(e))

    def _delete(self) -> None:
        if not self.ticket_id:
            return
        if not self.flush_pending():
            return
        ticket = self.controller.board.get(self.ticket_id)
        if ticket is None:
            return
        resp = QMessageBox.question(
            self,
            "SAIPLAN",
            f"Move {self.ticket_id} to Trash?\n\n{ticket.title}\n\n"
            f"You can restore it later from the Trash dialog.",
        )
        if resp == QMessageBox.StandardButton.Yes:
            try:
                self.controller.delete_ticket(self.ticket_id)
            except Exception as e:  # noqa: BLE001
                QMessageBox.warning(self, "SAIPLAN", str(e))
                return
            self.set_ticket(None)
            self.board_changed.emit()  # refresh board columns after deletion

    def _toggle_timer(self) -> None:
        if self.ticket_id and self.on_timer_toggle:
            self.on_timer_toggle(self.ticket_id)
            self._refresh_timer_state()

    def _open_notes(self) -> None:
        if self.ticket_id and self.on_notes:
            self.on_notes(self.ticket_id)

    # -- attachments --------------------------------------------------
    def _refresh_attachments(self) -> None:
        self.attach_list.clear()
        if not self.ticket_id or self.controller is None:
            self.attach_btn.setEnabled(False)
            self.attach_open_btn.setEnabled(False)
            self.attach_remove_btn.setEnabled(False)
            return
        for path in self.controller.list_attachments(self.ticket_id):
            item = QListWidgetItem(path.name)
            item.setData(Qt.ItemDataRole.UserRole, str(path))
            self.attach_list.addItem(item)
        self.attach_btn.setEnabled(self.controller.board.get(self.ticket_id) is not None)
        self._update_attach_actions()

    def _update_attach_actions(self) -> None:
        has_selection = self.attach_list.currentRow() >= 0 and bool(self.ticket_id)
        self.attach_open_btn.setEnabled(has_selection)
        self.attach_remove_btn.setEnabled(has_selection)

    def _attach_file(self) -> None:
        if not self.ticket_id or self.controller is None:
            return
        source, _filter = QFileDialog.getOpenFileName(self, "Attach file")
        if not source:
            return
        try:
            self.controller.attach_file(self.ticket_id, source)
        except (OSError, ValueError) as exc:
            self.save_failed.emit(f"Could not attach file: {exc}")
            return
        self._refresh_attachments()

    def _open_attachment(self) -> None:
        item = self.attach_list.currentItem()
        if item is None:
            return
        path = item.data(Qt.ItemDataRole.UserRole)
        if path and Path(path).is_file():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def _remove_attachment(self) -> None:
        item = self.attach_list.currentItem()
        if item is None or not self.ticket_id or self.controller is None:
            return
        name = item.text()
        try:
            self.controller.remove_attachment(self.ticket_id, name)
        except OSError as exc:
            self.save_failed.emit(f"Could not remove attachment: {exc}")
            return
        self._refresh_attachments()

    def after_board_change(self) -> None:
        """Re-sync the inspector when the board changed elsewhere."""
        if self.ticket_id:
            ticket = self.controller.board.get(self.ticket_id)
            self.set_ticket(ticket if ticket else None)
        else:
            self.set_ticket(None)
