"""Right inspector pane: selected ticket details, fields, checklist, actions.

Collapsible; hidden by default. Editing is autosaved — every field change is
persisted immediately (no Save button in the product's vocabulary).
"""

from __future__ import annotations

import json

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox,
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

SINGLE_LINE_FIELDS = (
    ("priority", "priority", "Priority"),
    ("due", "due", "Due"),
    ("tags", "tags", "Tags"),
    ("estimate", "estimate", "Estimate"),
    ("needs", "needs", "Needs"),
    ("done-when", "done-when", "Done when"),
)


class Inspector(QWidget):
    board_changed = pyqtSignal()

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
        self.details_edit.textChanged.connect(self._debounce.start)
        layout.addWidget(self.details_edit)

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

        layout.addStretch(1)
        self.setMinimumWidth(240)

    # -- display ------------------------------------------------------
    def set_ticket(self, ticket: Ticket | None) -> None:
        self._busy = True
        self.ticket_id = ticket.ticket_id if ticket else None
        if ticket is None:
            self.title_edit.clear()
            self.status_label.setText("No ticket selected")
            for edit in self.field_edits.values():
                edit.clear()
            self.priority_combo.setCurrentIndex(0)
            self.details_edit.setPlainText("")
            self._fill_checklist("")
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
            return
        self.title_edit.setText(ticket.title)
        self.status_label.setText(f"{ticket.ticket_id}  ·  {ticket.status}")
        for key, edit in self.field_edits.items():
            edit.setText(ticket.get(key))
        idx = self.priority_combo.findText(ticket.get("priority"))
        self.priority_combo.setCurrentIndex(max(0, idx))
        self.details_edit.setPlainText(ticket.get("details"))
        self._fill_checklist(ticket.get("checklist"))
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
    def _save_title(self) -> None:
        if self._busy or not self.ticket_id:
            return
        try:
            self.controller.edit_field(self.ticket_id, "title", self.title_edit.text())
            self.board_changed.emit()
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(self, "SAIPLAN", str(e))

    def _save_field(self, key: str, edit: QLineEdit) -> None:
        if self._busy or not self.ticket_id:
            return
        try:
            self.controller.edit_field(self.ticket_id, key, edit.text().strip())
            self.board_changed.emit()
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(self, "SAIPLAN", str(e))

    def _save_priority(self) -> None:
        if self._busy or not self.ticket_id:
            return
        self._save_field("priority", self.priority_combo)

    def _save_details(self) -> None:
        if self._busy or not self.ticket_id:
            return
        value = self.details_edit.toPlainText().strip().replace("\n", " ")
        try:
            self.controller.edit_field(self.ticket_id, "details", value)
            self.board_changed.emit()
        except Exception as e:  # noqa: BLE001
            self._log_save_error(e)

    def _serialize_checklist(self) -> str:
        out = []
        for i in range(self.checklist.count()):
            item = self.checklist.item(i)
            text = item.text()[2:]  # strip ☐/☑ marker
            out.append({"text": text, "done": bool(item.data(Qt.ItemDataRole.UserRole))})
        return json.dumps(out)

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
            self.board_changed.emit()
        except Exception as e:  # noqa: BLE001
            self._log_save_error(e)

    # -- actions ------------------------------------------------------
    def _transition(self, target: str, needs_reason: bool | None) -> None:
        if not self.ticket_id:
            return
        reason = None
        if needs_reason:
            label = "Why block?" if target == BLOCKED else "What lifts the block / why reopen?"
            reason, ok = QInputDialog.getText(self, "SAIPLAN", label)
            if not ok:
                return
        try:
            self.controller.transition(self.ticket_id, target, reason)
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(self, "SAIPLAN", str(e))

    def _delete(self) -> None:
        if not self.ticket_id:
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
            self.controller.delete_ticket(self.ticket_id)
            self.set_ticket(None)

    def _toggle_timer(self) -> None:
        if self.ticket_id and self.on_timer_toggle:
            self.on_timer_toggle(self.ticket_id)
            self._refresh_timer_state()

    def _open_notes(self) -> None:
        if self.ticket_id and self.on_notes:
            self.on_notes(self.ticket_id)

    @staticmethod
    def _log_save_error(error: Exception) -> None:
        import logging

        logging.getLogger("saiplan").debug("inspector autosave failed: %s", error)

    def after_board_change(self) -> None:
        """Re-sync the inspector when the board changed elsewhere."""
        if self.ticket_id:
            ticket = self.controller.board.get(self.ticket_id)
            self.set_ticket(ticket if ticket else None)
        else:
            self.set_ticket(None)
