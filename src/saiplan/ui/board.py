"""Kanban board view (ui/board.py).

Four columns (DOING/TODO/DONE/BLOCKED), drag/drop between them, keyboard
navigation, WIP badge, quick-add. Every important action is reachable WITHOUT
hovering: drag/drop, keyboard shortcuts (shell), the inspector, and the quick
add box all expose the same transitions.
"""

from __future__ import annotations

from PyQt6.QtCore import QMimeData, Qt, pyqtSignal
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QVBoxLayout,
    QWidget,
)

from ..core.model import BLOCKED, DOING, DONE, TODO

TICKET_MIME = "application/x-saiplan-ticket"

SECTIONS = (DOING, TODO, DONE, BLOCKED)

META_ORDER = ("priority", "due", "tags", "estimate", "needs", "done-when")


def ticket_meta(ticket) -> str:
    parts = []
    for key in META_ORDER:
        value = ticket.get(key)
        if not value:
            continue
        if key == "tags":
            value = " ".join(f"#{t.strip()}" for t in value.split(",") if t.strip())
        parts.append(f"{key}: {value}")
    return " · ".join(parts)


class ColumnWidget(QListWidget):
    """One board column. Accepts ticket drops and emits them to the board."""

    drop_requested = pyqtSignal(str, str)  # (ticket_id, section)
    context_requested = pyqtSignal(str)  # ticket_id

    def __init__(self, section: str, parent=None):
        super().__init__(parent)
        self.section = section
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._context_menu)

    def add_ticket(self, ticket) -> QListWidgetItem:
        item = QListWidgetItem()
        title = ticket.title.replace("\n", " ")
        meta = ticket_meta(ticket)
        item.setText(f"{ticket.ticket_id}  {title}" + (f"\n{meta}" if meta else ""))
        item.setData(Qt.ItemDataRole.UserRole, ticket.ticket_id)
        item.setToolTip(ticket.ticket_id)
        self.addItem(item)
        return item

    def selected_ticket_ids(self) -> list[str]:
        return [it.data(Qt.ItemDataRole.UserRole) for it in self.selectedItems()]

    # -- drag/drop ----------------------------------------------------
    def mimeTypes(self):
        return [TICKET_MIME, "text/plain"]

    def mimeData(self, items):
        mime = QMimeData()
        mime.setData(
            TICKET_MIME, ",".join(it.data(Qt.ItemDataRole.UserRole) for it in items).encode()
        )
        return mime

    def dropEvent(self, event):
        if event.mimeData().hasFormat(TICKET_MIME):
            ids = event.mimeData().data(TICKET_MIME).data().decode().split(",")
            for ticket_id in ids:
                if ticket_id:
                    self.drop_requested.emit(ticket_id, self.section)
            event.acceptProposedAction()
            return
        super().dropEvent(event)

    def _context_menu(self, pos):
        item = self.itemAt(pos)
        if item is None:
            return
        ticket_id = item.data(Qt.ItemDataRole.UserRole)
        menu = QMenu(self)
        for label, target in (
            ("Start", DOING),
            ("Done", DONE),
            ("Block", BLOCKED),
            ("Reopen / Unblock", TODO),
        ):
            act = QAction(label, self)
            act.triggered.connect(lambda _=False, t=target: self._action(ticket_id, t))
            menu.addAction(act)
        menu.addSeparator()
        open_act = QAction("Edit...", self)
        open_act.triggered.connect(lambda _=False: self.context_requested.emit(ticket_id))
        menu.addAction(open_act)
        menu.exec(self.viewport().mapToGlobal(pos))

    def _action(self, ticket_id: str, target: str):
        self.drop_requested.emit(ticket_id, target)


class QuickAdd(QLineEdit):
    def __init__(self, on_create, parent=None):
        super().__init__(parent)
        self._on_create = on_create
        self.setPlaceholderText("Add ticket and press Enter...")
        self.returnPressed.connect(self._submit)

    def _submit(self):
        text = self.text().strip()
        if not text:
            return
        ok = self._on_create(text)
        if ok:
            self.clear()  # keep the typed text on failure
        self.setFocus()


class BoardView(QWidget):
    """Four columns + quick-add. Re-rendered whole after each controller op."""

    ticket_dropped = pyqtSignal(str, str)
    ticket_activated = pyqtSignal(str)
    ticket_selected = pyqtSignal(list)
    mutation_succeeded = pyqtSignal()
    quick_add_failed = pyqtSignal(str)

    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.controller = controller
        self.columns: dict[str, ColumnWidget] = {}
        self._build()

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        self.quick_add = QuickAdd(self._on_quick_add)
        layout.addWidget(self.quick_add)

        cols = QHBoxLayout()
        cols.setSpacing(6)
        for section in SECTIONS:
            col = ColumnWidget(section)
            header = QLabel()
            header.setObjectName("sectionTitle")
            col.header = header
            wrapper = QVBoxLayout()
            wrapper.setSpacing(2)
            wrapper.addWidget(header)
            wrapper.addWidget(col)
            cols.addLayout(wrapper, 1)
            col.drop_requested.connect(lambda tid, s, col=col: self.ticket_dropped.emit(tid, s))
            col.context_requested.connect(self.ticket_activated)
            col.itemDoubleClicked.connect(lambda it, col=col: self._on_item_double(col, it))
            col.itemSelectionChanged.connect(self._on_selection)
            self.columns[section] = col
        layout.addLayout(cols, 1)

    def _on_item_double(self, col: ColumnWidget, item):
        tid = item.data(Qt.ItemDataRole.UserRole)
        if tid:
            self.ticket_activated.emit(tid)

    def _on_selection(self):
        ids = []
        for section in SECTIONS:
            ids.extend(self.columns[section].selected_ticket_ids())
        self.ticket_selected.emit(ids)

    def _on_quick_add(self, title: str) -> bool:
        """Create via the controller; on success signal the shell to refresh.
        Returns True so QuickAdd clears only on success (failure keeps the
        typed text). Errors surface non-modally through the signal so the app
        never blocks on a message box."""
        try:
            self.controller.create_ticket(title)
        except Exception as e:  # noqa: BLE001
            self.quick_add_failed.emit(str(e))
            return False
        self.mutation_succeeded.emit()
        return True

    def focus_quick_add(self) -> None:
        self.quick_add.setFocus()

    def set_search(self, ids: list[str] | None) -> None:
        """Filter columns to the given ticket ids (None = no filter)."""
        limits = {}
        single_focus = False
        if self.controller is not None and self.controller.config is not None:
            limits = self.controller.config.get("wip_limits") or {}
            single_focus = bool(self.controller.config.get("single_focus", True))
        for section, col in self.columns.items():
            col.clear()
            for _s, ticket in self.controller.board:
                if ticket.status != section:
                    continue
                if ids is not None and ticket.ticket_id not in ids:
                    continue
                col.add_ticket(ticket)
            count = col.count()
            limit = limits.get(section)
            header = f"{section}  ({count}" + (f"/{limit}" if limit else "") + ")"
            over_limit = bool(limit) and count > limit
            if (section == DOING and count > 1 and single_focus) or over_limit:
                header += "  !"
            col.header.setText(header)

    def selected_tickets(self) -> list:
        out = []
        for section in SECTIONS:
            for tid in self.columns[section].selected_ticket_ids():
                t = self.controller.board.get(tid)
                if t:
                    out.append(t)
        return out
