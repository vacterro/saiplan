"""Main window: plan list, board, inspector, toolbar, shortcuts, wiring.

One controller per open plan. Autosave is the default; there is no Save
button in the product's vocabulary. Extras (timers/sounds/themes) degrade
silently — a failure never prevents the board from working (I1, I8).
"""

from __future__ import annotations

from PyQt6.QtCore import QSignalBlocker, Qt, QTimer, QUrl
from PyQt6.QtGui import QAction, QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QApplication,
    QDockWidget,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..core.config import Config
from ..core.model import BLOCKED, DOING, DONE, TODO
from ..core.persistence import BoardStore
from ..core.plan import PlanStore
from ..extras.sounds import (
    NullSoundLibrary,
    NullSoundPlayer,
    NullSoundRegistry,
    SoundLibrary,
    SoundPlayer,
    SoundRegistry,
)
from ..extras.timers import TicketTimer
from ..theme.loader import build_qss
from ..theme.registry import ThemeRegistry
from .board import BoardView
from .controller import BoardController, ControllerError
from .dialogs import (
    BreakDownDialog,
    ConflictDialog,
    PlanDialog,
    RecoveryDialog,
    ReviewDialog,
    SettingsDialog,
    SoundDialog,
    StatsDialog,
    TimerPanel,
    TrashDialog,
)
from .inspector import Inspector


class App:
    """Application wiring shared by shell and dialogs."""

    def __init__(
        self, layout: dict, config: Config, theme_registry: ThemeRegistry | None, timer_engine
    ):
        self.layout = layout
        self.config = config
        # I8: a failed registry construction must never leave None downstream;
        # normalize to a real registry that falls back to the emergency theme
        self.theme_registry = theme_registry or ThemeRegistry(layout["themes"])
        self.plan_store = PlanStore(layout["plans"])
        try:
            self.sound_library = SoundLibrary(layout["sounds"])
            self.sound_registry = SoundRegistry(
                self.sound_library, config.get("sound_events") or {}
            )
            self.sound_player = SoundPlayer()
        except Exception as error:  # noqa: BLE001 - optional sound cannot block Core
            import logging

            logging.getLogger("saiplan").error("sound subsystem disabled: %s", error)
            self.sound_library = NullSoundLibrary()
            self.sound_registry = NullSoundRegistry()
            self.sound_player = NullSoundPlayer()
        self.timer_engine = timer_engine
        self.controller: BoardController | None = None
        self.ticket_timer: TicketTimer | None = None


class MainWindow(QMainWindow):
    def __init__(self, app: App):
        super().__init__()
        self.app = app
        self.setWindowTitle("SAIPLAN")
        self.setMinimumSize(980, 600)

        # timers first: _build_ui wires signals to them
        self._conflict_timer = QTimer(self)
        self._conflict_timer.setInterval(2000)
        self._conflict_timer.timeout.connect(self._poll_external)
        self._conflict_timer.start()
        self._conflict_shown = False

        self._tick_timer = QTimer(self)
        self._tick_timer.setInterval(1000)
        self._tick_timer.timeout.connect(self._tick)
        self._tick_timer.start()

        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(200)
        self._search_timer.timeout.connect(self._apply_search)

        self._build_ui()
        self._build_shortcuts()
        self._apply_theme()
        self._restore_geometry()

        self._load_plans()
        self._open_initial()

    # -- UI -----------------------------------------------------------
    def _build_ui(self):
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(4, 4, 4, 4)
        create_btn = QPushButton("New Plan")
        create_btn.clicked.connect(self._new_plan)
        left_layout.addWidget(create_btn)
        import_btn = QPushButton("Import Plan...")
        import_btn.clicked.connect(self._import_plan)
        left_layout.addWidget(import_btn)
        self.plan_list = QListWidget()
        self.plan_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.plan_list.customContextMenuRequested.connect(self._plan_menu)
        self.plan_list.itemSelectionChanged.connect(self._on_plan_selected)
        left_layout.addWidget(self.plan_list, 1)
        left.setMaximumWidth(220)
        left.setMinimumWidth(170)

        self.board_view = BoardView(controller=None)
        self.board_view.ticket_dropped.connect(self._on_drop)
        self.board_view.ticket_activated.connect(self._on_activate)
        self.board_view.ticket_selected.connect(self._on_tickets_selected)
        self.board_view.mutation_succeeded.connect(self._after_mutation)
        self.board_view.quick_add_failed.connect(lambda message: self.status.showMessage(message))

        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("Search (Ctrl+F)...")
        self.search_box.textChanged.connect(self._search_timer.start)

        central = QWidget()
        central_layout = QVBoxLayout(central)
        central_layout.setContentsMargins(4, 4, 4, 4)
        self.conflict_banner = QLabel("BOARD.md changed externally — click to resolve")
        self.conflict_banner.setObjectName("conflictBanner")
        self.conflict_banner.setStyleSheet(
            "background: #7A2020; color: #FFFFFF; padding: 6px; font-weight: bold;"
        )
        self.conflict_banner.hide()
        self.conflict_banner.mousePressEvent = lambda _e: self._resolve_conflict()
        central_layout.addWidget(self.conflict_banner)
        central_layout.addWidget(self.search_box)
        central_layout.addWidget(self.board_view, 1)

        self.inspector = Inspector(
            self.app.controller,
            ticket_timer=None,
            on_timer_toggle=self._toggle_ticket_timer,
            on_notes=self._open_notes,
        )
        self.inspector.board_changed.connect(self._after_mutation)
        self.inspector.save_failed.connect(
            lambda message: self.status.showMessage(f"WARNING: {message}", 10000)
        )
        self.inspector_dock = QDockWidget("Ticket", self)
        self.inspector_dock.setObjectName("inspectorDock")
        self.inspector_dock.setWidget(self.inspector)
        self.inspector_dock.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetMovable
            | QDockWidget.DockWidgetFeature.DockWidgetFloatable
        )
        self.inspector_dock.hide()

        toolbar = self.addToolBar("main")
        toolbar.setMovable(False)
        for label, slot in (
            ("New ticket", self._focus_new_ticket),
            ("Break down", self._break_down),
            ("Plan review", self._plan_review),
            ("Timers", self._open_timers),
            ("Sounds", self._open_sounds),
            ("Statistics", self._open_stats),
            ("Recovery", self._open_recovery),
            ("Trash", self._open_trash),
            ("Settings", self._open_settings),
        ):
            toolbar.addAction(QAction(label, self, triggered=slot))

        self.status = self.statusBar()
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.inspector_dock)
        self.setCentralWidget(central)

        left_wrap = QWidget()
        lw = QHBoxLayout(left_wrap)
        lw.setContentsMargins(0, 0, 0, 0)
        lw.addWidget(left)
        self.left_dock = QDockWidget("Plans", self)
        self.left_dock.setObjectName("plansDock")
        self.left_dock.setWidget(left_wrap)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self.left_dock)

    def _build_shortcuts(self):
        def bind(key, slot, context=None):
            sc = QShortcut(QKeySequence(key), self)
            sc.activated.connect(slot)
            return sc

        bind("Ctrl+N", self._focus_new_ticket)
        bind("Ctrl+Shift+N", self._new_plan)
        bind("Ctrl+Enter", lambda: self._on_selected_action(DOING))
        bind("Ctrl+D", lambda: self._on_selected_action(DONE))
        bind("Ctrl+B", lambda: self._on_selected_action(BLOCKED))
        bind("Ctrl+Shift+R", lambda: self._on_selected_action(TODO))
        bind("Ctrl+F", lambda: self.search_box.setFocus())
        bind("Ctrl+Z", self._undo)
        bind("Ctrl+Shift+Z", self._redo)
        bind("Delete", self._delete_selected)
        bind("Space", self._space_action)
        for i, section in enumerate((DOING, TODO, DONE, BLOCKED), 1):
            bind(f"Ctrl+{i}", lambda s=section: self._focus_section(s))

    # -- plans ---------------------------------------------------------
    def _load_plans(self):
        self.plan_list.clear()
        plans = self.app.plan_store.list_plans()
        pinned = set(self.app.config.get("pinned_plans") or [])
        order = sorted(plans, key=lambda p: (p.plan_id not in pinned, p.name.lower()))
        self._plans = {p.plan_id: p for p in plans}
        for p in order:
            item = QListWidgetItem(("📌 " if p.plan_id in pinned else "") + p.name)
            item.setData(Qt.ItemDataRole.UserRole, p.plan_id)
            self.plan_list.addItem(item)

    def _on_plan_selected(self):
        item = self.plan_list.currentItem()
        if item is None:
            return
        plan = self._plans.get(item.data(Qt.ItemDataRole.UserRole))
        if plan and not self._open_plan(plan):
            self._select_active_plan()

    def _select_active_plan(self) -> None:
        controller = self.app.controller
        if controller is None:
            return
        with QSignalBlocker(self.plan_list):
            for row in range(self.plan_list.count()):
                item = self.plan_list.item(row)
                if item.data(Qt.ItemDataRole.UserRole) == controller.plan.plan_id:
                    self.plan_list.setCurrentRow(row)
                    break

    def _plan_menu(self, pos):
        item = self.plan_list.itemAt(pos)
        if item is None:
            return
        plan_id = item.data(Qt.ItemDataRole.UserRole)
        pinned = self.app.config.get("pinned_plans") or []
        menu = QMenu(self)
        act = QAction("Unpin" if plan_id in pinned else "Pin", self)
        act.triggered.connect(lambda _=False: self._toggle_pin(plan_id))
        menu.addAction(act)
        rename = QAction("Rename...", self)
        rename.triggered.connect(lambda _=False: self._rename_plan(plan_id))
        menu.addAction(rename)
        export = QAction("Export plan...", self)
        export.triggered.connect(lambda _=False: self._export_plan(plan_id))
        menu.addAction(export)
        archive = QAction("Archive", self)
        archive.triggered.connect(lambda _=False: self._archive_plan(plan_id))
        menu.addAction(archive)
        menu.exec(self.plan_list.viewport().mapToGlobal(pos))

    def _toggle_pin(self, plan_id: str):
        pinned = list(self.app.config.get("pinned_plans") or [])
        if plan_id in pinned:
            pinned.remove(plan_id)
        else:
            pinned.append(plan_id)
        self.app.config.set("pinned_plans", pinned)
        self.app.config.save()
        self._load_plans()

    def _rename_plan(self, plan_id: str):
        plan = self._plans.get(plan_id)
        if plan is None:
            return
        name, ok = QInputDialog.getText(self, "Rename plan", "Name", text=plan.name)
        if ok and name.strip():
            # surgical update: keeps Objective/Constraints/DoD + unknown sections
            plan.update_plan_doc(name=name.strip())
            self._load_plans()

    def _export_plan(self, plan_id: str):
        from ..core.bundle import export_plan

        plan = self._plans.get(plan_id)
        if plan is None:
            return
        # flush any pending inspector draft so notes leave the window too
        if self.app.controller is not None and plan_id == self.app.controller.plan.plan_id:
            self.inspector.flush_pending()
        default_name = f"{plan.name}.saiplan"
        target, _filter = QFileDialog.getSaveFileName(
            self, "Export plan", default_name, "SAIPLAN bundle (*.saiplan)"
        )
        if not target:
            return
        try:
            export_plan(plan, target)
        except OSError as exc:
            QMessageBox.warning(self, "Export failed", str(exc))
            return
        self.status.showMessage(f"Plan '{plan.name}' exported", 6000)

    def _import_plan(self):
        from ..core.bundle import BundleError, import_plan

        source, _filter = QFileDialog.getOpenFileName(
            self, "Import plan", "", "SAIPLAN bundle (*.saiplan)"
        )
        if not source:
            return
        try:
            plan = import_plan(self.app.layout["plans"], source)
        except (BundleError, OSError) as exc:
            QMessageBox.warning(self, "Import refused", str(exc))
            return
        recent = list(self.app.config.get("recent_plans") or [])
        self.app.config.set(
            "recent_plans", [plan.plan_id] + [p for p in recent if p != plan.plan_id]
        )
        self.app.config.save()
        self._load_plans()
        self._open_plan(plan)
        self.status.showMessage(f"Plan '{plan.name}' imported", 6000)

    def _new_plan(self):
        dialog = PlanDialog(self)
        if dialog.exec() == PlanDialog.DialogCode.Accepted:
            name, objective = dialog.values()
            if not name:
                return
            plan = self.app.plan_store.create(name, objective)
            self.app.config.set(
                "recent_plans", [plan.plan_id] + (self.app.config.get("recent_plans") or [])
            )
            self.app.config.save()
            self._load_plans()
            self._open_plan(plan)

    def _archive_plan(self, plan_id: str):
        from ..extras.archive import archive_plan

        resp = QMessageBox.question(
            self,
            "SAIPLAN",
            f"Archive plan '{plan_id}'? It moves to data/archive/ and can be "
            f"restored by moving it back.",
        )
        if resp != QMessageBox.StandardButton.Yes:
            return
        # if the archived plan is the one the controller is using, detach it
        # cleanly first so a later mutation cannot recreate its old directory
        controller = self.app.controller
        if (
            controller is not None
            and controller.plan.plan_id == plan_id
            and not self._detach_active_plan()
        ):
            return
        recent = list(self.app.config.get("recent_plans") or [])
        pinned = list(self.app.config.get("pinned_plans") or [])
        for lst in (recent, pinned):
            if plan_id in lst:
                lst.remove(plan_id)
        self.app.config.set("recent_plans", recent)
        self.app.config.set("pinned_plans", pinned)
        self.app.config.save()
        if archive_plan(self.app.layout["plans"], plan_id) is not None:
            self._load_plans()
            self._open_initial()

    def _detach_active_plan(self):
        """Stop ticket timers and drop the controller before archiving the
        active plan."""
        if not self.inspector.flush_pending():
            return False
        if self.app.ticket_timer is not None:
            try:
                self.app.ticket_timer.stop_all()
            except OSError as error:
                self.status.showMessage(f"WARNING: could not close ticket timers: {error}")
                return False
        self.app.controller = None
        self.app.ticket_timer = None
        self.board_view.controller = None
        self.inspector.controller = None
        self._conflict_shown = False
        self.conflict_banner.hide()
        self.setWindowTitle("SAIPLAN")
        self.status.showMessage("Plan archived")
        return True

    def _open_initial(self):
        plans = self.app.plan_store.list_plans()
        if not plans:
            self._new_plan()
            return
        recent = self.app.config.get("recent_plans") or []
        target = None
        for pid in recent:
            if pid in self._plans:
                target = self._plans[pid]
                break
        target = target or plans[0]
        self._open_plan(target)
        # fresh-plan focus: new users type immediately
        self.board_view.focus_quick_add()

    # -- controller ----------------------------------------------------
    def _open_plan(self, plan):
        if self.app.controller is not None and not self.inspector.flush_pending():
            self.status.showMessage("WARNING: plan switch blocked by unsaved ticket changes")
            return False
        mirror_dir = self.app.config.get("mirror_dir") or None
        store = BoardStore(
            plan.board_path,
            plan.history_dir,
            mirror_dir=mirror_dir,
            snapshot_keep=self.app.config.get("snapshot_keep", 14),
            mirror=self.app.config.get("mirror_enabled", False),
        )
        controller = BoardController(plan, store, self.app.config)
        controller.load()
        same_plan = (
            self.app.controller is not None
            and self.app.controller.plan.plan_id == plan.plan_id
            and self.app.ticket_timer is not None
        )
        if same_plan:
            ticket_timer = self.app.ticket_timer
        else:
            try:
                ticket_timer = TicketTimer(plan.timelog_path)
            except OSError as error:
                self.status.showMessage(f"WARNING: ticket timers disabled for this plan: {error}")
                ticket_timer = None
        if self.app.ticket_timer is not None and not same_plan:
            try:
                self.app.ticket_timer.stop_all()
            except OSError as error:
                self.status.showMessage(f"WARNING: plan switch blocked by ticket timer: {error}")
                return False
        self.app.controller = controller
        self.app.ticket_timer = ticket_timer
        self.app.timer_engine.ticket_timer = ticket_timer
        self.inspector.controller = controller
        self.inspector.clear_preserved_conflict_draft()
        self.inspector.ticket_timer = ticket_timer
        self.board_view.controller = controller
        self._conflict_shown = False
        self.conflict_banner.hide()
        self._refresh()
        self.setWindowTitle(f"SAIPLAN — {plan.name}")
        self.status.showMessage(f"{plan.plan_id}  ·  {plan.objective[:80]}")
        recent = [plan.plan_id] + [
            p for p in (self.app.config.get("recent_plans") or []) if p != plan.plan_id
        ]
        self.app.config.set("recent_plans", recent[:10])
        self.app.config.save()
        return True

    def _refresh(self):
        controller = self.app.controller
        if controller is None:
            return
        self.board_view.set_search(self._current_filter())
        self.inspector.after_board_change()
        counts = controller.board.counts()
        self.status.showMessage(
            f"DOING {counts[DOING]}  ·  TODO {counts[TODO]}  ·  "
            f"DONE {counts[DONE]}  ·  BLOCKED {counts[BLOCKED]}"
            + (f"   ({controller.warnings[0]})" if controller.warnings else "")
        )

    def _current_filter(self) -> list[str] | None:
        q = self.search_box.text().strip()
        if not q or self.app.controller is None:
            return None
        from ..core.search import Searcher

        searcher = Searcher()
        searcher.refresh(self.app.controller.board)
        return [r["id"] for r in searcher.search(q)]

    def _apply_search(self):
        self.board_view.set_search(self._current_filter())

    # -- board actions -------------------------------------------------
    def _focus_new_ticket(self):
        self.board_view.focus_quick_add()

    def _focus_section(self, section: str):
        col = self.board_view.columns[section]
        col.setFocus()
        if col.count():
            col.setCurrentRow(0)

    def _on_drop(self, ticket_id: str, target: str):
        controller = self.app.controller
        if controller is None:
            return
        if self.inspector.ticket_id == ticket_id and not self.inspector.flush_pending():
            return
        ticket = controller.board.get(ticket_id)
        if ticket is None or ticket.status == target:
            return
        reason = None
        if target == BLOCKED:
            reason, ok = QInputDialog.getText(
                self, "Block ticket", "Why is it blocked?", text="waiting for "
            )
            if not ok:
                return
        elif target == TODO and ticket.status == BLOCKED:
            reason, ok = QInputDialog.getText(
                self, "Unblock ticket", "What lifts the block?", text=""
            )
            if not ok:
                return
        try:
            controller.transition(ticket_id, target, reason)
            self._after_mutation()
        except ControllerError as e:
            QMessageBox.warning(self, "SAIPLAN", str(e))

    def _after_mutation(self):
        """Refresh the board and map the last committed semantic event to an
        optional sound. Core never depends on sound — this is the UI adapter."""
        self._refresh()
        controller = self.app.controller
        if controller is None:
            return
        event = controller.last_event
        if event == "TICKET_DONE":
            self._play("ticket_done")
        elif event == "TICKET_BLOCKED":
            self._play("blocked_warning")
        if event == "TICKET_DONE" and self._plan_just_completed(controller):
            self._play("plan_completed")
        controller.last_event = None

    def _on_selected_action(self, target: str):
        controller = self.app.controller
        if controller is None:
            return
        tickets = self.board_view.selected_tickets()
        if not tickets:
            return
        ticket = tickets[0]
        self._on_drop(ticket.ticket_id, target)

    def _delete_selected(self):
        controller = self.app.controller
        if controller is None:
            return
        tickets = self.board_view.selected_tickets()
        if not tickets:
            return
        ids = [t.ticket_id for t in tickets]
        resp = QMessageBox.question(
            self, "SAIPLAN", f"Move {len(ids)} ticket(s) to Trash? They can be restored later."
        )
        if resp != QMessageBox.StandardButton.Yes:
            return
        if self.inspector.ticket_id in ids and not self.inspector.flush_pending():
            return
        for tid in ids:
            try:
                controller.delete_ticket(tid)
            except Exception as e:  # noqa: BLE001
                QMessageBox.warning(self, "SAIPLAN", str(e))
        self._on_board_mutated()

    def _on_activate(self, ticket_id: str):
        self.inspector_dock.show()
        ticket = self.app.controller.board.get(ticket_id) if self.app.controller else None
        self.inspector.set_ticket(ticket)

    def _on_tickets_selected(self, ids: list[str]):
        if not ids:
            return
        self.inspector_dock.show()
        ticket = self.app.controller.board.get(ids[0]) if self.app.controller else None
        self.inspector.set_ticket(ticket)

    def _on_board_mutated(self):
        """Legacy alias: every mutation path funnels through _after_mutation."""
        self._after_mutation()

    @staticmethod
    def _plan_just_completed(controller) -> bool:
        """True when no open tickets remain and at least one is DONE."""
        counts = controller.board.counts()
        return (
            counts[TODO] == 0 and counts[DOING] == 0 and counts[BLOCKED] == 0 and counts[DONE] > 0
        )

    def _undo(self):
        if self.app.controller and self.app.controller.undo():
            self._play("undo")
            self._refresh()

    def _redo(self):
        if self.app.controller and self.app.controller.redo():
            self._refresh()

    def _space_action(self):
        widget = QApplication.focusWidget()
        if isinstance(widget, (QLineEdit, QPushButton)):
            return  # let text boxes and buttons take Space
        controller = self.app.controller
        if controller is None:
            return
        tickets = self.board_view.selected_tickets()
        if tickets:
            self._toggle_ticket_timer(tickets[0].ticket_id)

    def _toggle_ticket_timer(self, ticket_id: str):
        tt = self.app.ticket_timer
        if tt is None:
            return
        running = tt.toggle(ticket_id)
        self.inspector._refresh_timer_state()
        self.status.showMessage("Timer running" if running else "Timer stopped")

    def _open_notes(self, ticket_id: str):
        plan = self.app.controller.plan if self.app.controller else None
        if plan is None:
            return
        from ..extras.notes import note_path, write_note

        path = note_path(plan, ticket_id)
        if not path.exists():
            ticket = self.app.controller.board.get(ticket_id)
            title = ticket.title if ticket else ticket_id
            path = write_note(plan, ticket_id, f"# {ticket_id} - {title}\n\n")
        QDesktop.open(path)

    # -- dialogs -------------------------------------------------------
    def _break_down(self):
        if self.app.controller is None:
            return
        dialog = BreakDownDialog(self)
        if dialog.exec() != BreakDownDialog.DialogCode.Accepted:
            return
        data = dialog.plan()
        if not data["tasks"]:
            return
        from ..core.proposal import PlanProposal, TaskProposal

        tasks = []
        for line in data["tasks"]:
            title, _, opts = line.partition("::")
            title = title.strip()
            if not title:
                continue
            task = TaskProposal(title=title)
            for opt in [o for o in opts.split("::")]:
                key, _, value = opt.strip().partition("=")
                key, value = key.strip(), value.strip()
                if key == "needs":
                    task.needs = [n.strip() for n in value.split(",") if n.strip()]
                elif key == "priority":
                    task.priority = value
                elif key == "due":
                    task.due = value
                elif key == "done-when":
                    task.done_when = value
            tasks.append(task)
        proposal = PlanProposal(
            goal=data["goal"] or "Plan",
            constraints=data["constraints"],
            definition_of_done=data["dod"],
            tasks=tasks,
        )
        controller = self.app.controller
        # validate ALL before showing a preview — never partial creation
        from ..core.proposal import validate_proposal

        problems = validate_proposal(proposal)
        if problems:
            ReviewDialog([("warn", "", m) for m in problems], self).exec()
            return
        # preview before commit
        preview = "\n".join(
            f"  - {t.title}" + (f"  (needs {', '.join(t.needs)})" if t.needs else "")
            for t in proposal.tasks
        )
        ok = QMessageBox.question(
            self,
            "SAIPLAN",
            f"Create {len(proposal.tasks)} ticket(s) in TODO?\n\n{preview}",
        )
        if ok != QMessageBox.StandardButton.Yes:
            return
        try:
            created = controller.accept_proposal(proposal)
        except ControllerError as e:
            QMessageBox.warning(self, "SAIPLAN", str(e))
            return
        self._after_mutation()
        ids = ", ".join(t.ticket_id for t in created)
        message = f"Broken down into {len(created)} ticket(s): {ids}"
        if controller.last_result.warnings:
            message += f"; WARNING: {controller.last_result.warnings[-1]}"
        self.status.showMessage(message)

    def _plan_review(self):
        if self.app.controller is None:
            return
        findings = self.app.controller.review()
        ReviewDialog(findings, self).exec()
        from ..core.logbook import append_event

        append_event(self.app.controller.plan.log_path, "PLAN_REVIEWED")

    def _open_timers(self):
        TimerPanel(self.app.timer_engine, self).exec()

    def _open_sounds(self):
        SoundDialog(
            self.app.sound_library, self.app.sound_registry, self.app.sound_player, self
        ).exec()
        self.app.config.set("sound_events", self.app.sound_registry.to_config())
        self.app.config.save()

    def _open_stats(self):
        if self.app.controller is None:
            return
        StatsDialog(self.app.controller, self).exec()

    def _open_recovery(self):
        if self.app.controller is None:
            return
        RecoveryDialog(self.app.controller, self).exec()
        self._refresh()

    def _open_trash(self):
        TrashDialog(self.app.controller, self).exec()
        self._refresh()

    def _open_settings(self):
        names = [t.slug for t in self.app.theme_registry.list_themes()]
        dialog = SettingsDialog(self.app.config, names, self)
        if dialog.exec() != SettingsDialog.DialogCode.Accepted:
            return
        values = dialog.values()
        for key, value in values.items():
            self.app.config.set(key, value)
        self.app.config.save()
        self._apply_theme()
        # always-on-top must be applied in BOTH directions, not just True
        self.setWindowFlag(
            Qt.WindowType.WindowStaysOnTopHint, bool(self.app.config.get("always_on_top", False))
        )
        self.show()
        # mirror setting takes effect on next plan open
        self.status.showMessage("Settings saved (mirror applies on next plan open)")

    # -- theme ---------------------------------------------------------
    def _apply_theme(self):
        requested = self.app.config.get("theme") or "goldenvintage"
        theme = self.app.theme_registry.get(requested)
        qss = build_qss(theme.tokens, float(self.app.config.get("scale", 1.0)))
        QApplication.instance().setStyleSheet(qss)
        self.app.config.set("theme", theme.slug)
        if requested != theme.slug:
            self.app.config.save()

    # -- sounds --------------------------------------------------------
    def _play(self, event: str):
        if not self.app.config.get("sound_enabled", True):
            return
        path = self.app.sound_registry.file_for(event)
        if path is None:
            return
        volume = int(self.app.config.get("sound_volume", 5)) / 10.0
        self.app.sound_player.play_file(path, volume * self.app.sound_registry.volume_for(event))

    # -- external edits -------------------------------------------------
    def _poll_external(self):
        controller = self.app.controller
        if controller is None:
            return
        if controller.has_external_change():
            if not self._conflict_shown:
                self._conflict_shown = True
                self.conflict_banner.show()
        else:
            # conflict resolved or never happened: re-arm for the next one
            self._conflict_shown = False
            self.conflict_banner.hide()

    def _resolve_conflict(self):
        controller = self.app.controller
        if controller is None:
            return
        self.conflict_banner.hide()
        dialog = ConflictDialog(self)
        choice = dialog.exec()
        if choice == 1:  # reload external (local preserved in a conflict copy)
            if not self.inspector.preserve_pending_for_conflict():
                return
            try:
                path = controller.resolve_reload_external()
            except ControllerError as e:
                QMessageBox.warning(self, "SAIPLAN", str(e))
                self._conflict_shown = False
                return
            self.inspector.reconcile_after_conflict()
            self._refresh()
            if path:
                self.status.showMessage(f"Reloaded external; local preserved in {path}")
        elif choice == 2:  # keep mine (external preserved in a conflict copy)
            if not self.inspector.preserve_pending_for_conflict():
                return
            try:
                path = controller.resolve_keep_mine()
            except ControllerError as e:
                QMessageBox.warning(self, "SAIPLAN", str(e))
                self._conflict_shown = False
                return
            self.inspector.reconcile_after_conflict()
            self._refresh()
            if path:
                self.status.showMessage(f"Kept local; external preserved in {path}")
        # a resolved conflict must re-arm the detector for the next one
        self._conflict_shown = False

    # -- timer engine --------------------------------------------------
    def _tick(self):
        engine = self.app.timer_engine
        fired = engine.tick()
        for timer in fired:
            self._play("timer_finished")
            self.status.showMessage(f"Timer finished: {timer.label}", 8000)
        event = engine.tick_pomodoro()
        if event:
            if event.completed_phase == "work":
                self._play("pomodoro_work_done")
                self.status.showMessage("Pomodoro work session done - take a break", 8000)
            else:
                self._play("break_finished")
                self.status.showMessage("Break over - back to work", 8000)

    # -- persistence of window state ------------------------------------
    def _restore_geometry(self):
        geom = self.app.config.get("window_geometry") or ""
        if geom:
            try:
                self.restoreGeometry(bytes.fromhex(geom))
            except (ValueError, TypeError):
                pass
        if self.app.config.get("always_on_top"):
            self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)

    def closeEvent(self, event):
        if not self.inspector.flush_pending():
            self.status.showMessage("WARNING: close blocked by unsaved ticket changes")
            event.ignore()
            return
        if self.app.ticket_timer is not None:
            try:
                self.app.ticket_timer.stop_all()
            except OSError as error:
                self.status.showMessage(f"WARNING: close blocked by ticket timer: {error}")
                event.ignore()
                return
        geom = bytes(self.saveGeometry()).hex()
        self.app.config.set("window_geometry", geom)
        self.app.config.save()
        self.app.timer_engine.save()
        event.accept()


class QDesktop:
    """Thin wrapper so the shell can be imported headless in tests."""

    @staticmethod
    def open(path: str):
        from PyQt6.QtGui import QDesktopServices

        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
