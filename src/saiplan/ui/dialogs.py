"""Dialogs: plan, break-down wizard, settings, sounds, timers, trash, review.

Every dialog returns plain data; the shell applies it. No dialog mutates the
board by itself — one writer (controller) keeps conflicts impossible.
"""

from __future__ import annotations

import datetime
import time
from datetime import UTC
from pathlib import Path

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSlider,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..extras.timers import parse_iso


class PlanDialog(QDialog):
    """First-run: name + objective. No wizard maze."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Create Plan")
        self.setMinimumWidth(420)
        layout = QVBoxLayout(self)
        title = QLabel("What do you want to accomplish?")
        title.setObjectName("sectionTitle")
        layout.addWidget(title)
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("Plan name")
        layout.addWidget(self.name_edit)
        self.objective_edit = QPlainTextEdit()
        self.objective_edit.setPlaceholderText("The goal. One or two sentences is enough.")
        self.objective_edit.setMaximumHeight(120)
        layout.addWidget(self.objective_edit)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.name_edit.setFocus()

    def values(self) -> tuple[str, str]:
        return self.name_edit.text().strip(), self.objective_edit.toPlainText().strip()


class BreakDownDialog(QDialog):
    """SAIPEN planning discipline, human-sized (spec 5).

    GOAL -> constraints -> definition of done -> atomic tasks -> deps.
    Task lines: `Title :: needs=S-3,S-4 :: priority=high`
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Break down the goal")
        self.setMinimumSize(520, 460)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.goal = QPlainTextEdit()
        self.goal.setPlaceholderText("What needs to be achieved?")
        self.goal.setMaximumHeight(70)
        self.constraints = QLineEdit()
        self.constraints.setPlaceholderText("budget, time, tools, limits...")
        self.dod = QLineEdit()
        self.dod.setPlaceholderText("how will you know it is done?")
        form.addRow("Goal", self.goal)
        form.addRow("Constraints", self.constraints)
        form.addRow("Done when", self.dod)
        layout.addLayout(form)
        tasks_label = QLabel("Atomic tasks (one per line):")
        tasks_label.setObjectName("sectionTitle")
        layout.addWidget(tasks_label)
        self.tasks = QPlainTextEdit()
        self.tasks.setPlaceholderText("Buy SSD\nResearch models :: needs=S-3\nInstall :: needs=S-1")
        layout.addWidget(self.tasks, 1)
        hint = QLabel("Optional per line:  title :: needs=S-1,S-2 :: priority=high")
        hint.setObjectName("sectionTitle")
        layout.addWidget(hint)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.tasks.setFocus()

    def plan(self) -> dict:
        return {
            "goal": self.goal.toPlainText().strip(),
            "constraints": self.constraints.text().strip(),
            "dod": self.dod.text().strip(),
            "tasks": [l.strip() for l in self.tasks.toPlainText().splitlines() if l.strip()],
        }


class SettingsDialog(QDialog):
    def __init__(self, config, theme_names: list[str], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        layout = QFormLayout(self)
        self.theme_combo = QComboBox()
        self.theme_combo.addItems(theme_names)
        idx = self.theme_combo.findText(config.get("theme", ""))
        if idx >= 0:
            self.theme_combo.setCurrentIndex(idx)
        layout.addRow("Theme", self.theme_combo)

        self.scale_combo = QComboBox()
        for s in (0.75, 0.85, 1.0, 1.15, 1.25, 1.5):
            self.scale_combo.addItem(f"{s:.2f}", s)
        self.scale_combo.setCurrentIndex(self.scale_combo.findData(float(config.get("scale", 1.0))))
        layout.addRow("Zoom", self.scale_combo)

        self.focus_check = QCheckBox("Single focus (one ticket in DOING)")
        self.focus_check.setChecked(bool(config.get("single_focus", True)))
        layout.addRow(self.focus_check)

        self.always_on_top = QCheckBox("Always on top")
        self.always_on_top.setChecked(bool(config.get("always_on_top", False)))
        layout.addRow(self.always_on_top)

        self.keep_spin = QSpinBox()
        self.keep_spin.setRange(1, 200)
        self.keep_spin.setValue(int(config.get("snapshot_keep", 14)))
        layout.addRow("Keep snapshots", self.keep_spin)

        self.mirror_check = QCheckBox("One-way mirror (write-only backup)")
        self.mirror_check.setChecked(bool(config.get("mirror_enabled", False)))
        layout.addRow(self.mirror_check)
        self.mirror_edit = QLineEdit(str(config.get("mirror_dir", "")))
        self.mirror_edit.setPlaceholderText("C:/path/to/mirror")
        browse = QPushButton("Browse...")
        browse.clicked.connect(self._browse_mirror)
        row = QHBoxLayout()
        row.addWidget(self.mirror_edit, 1)
        row.addWidget(browse)
        layout.addRow("Mirror folder", row)

        self.sound_check = QCheckBox("Sound effects")
        self.sound_check.setChecked(bool(config.get("sound_enabled", True)))
        layout.addRow(self.sound_check)
        self.volume = QSlider(Qt.Orientation.Horizontal)
        self.volume.setRange(0, 10)
        self.volume.setValue(int(config.get("sound_volume", 5)))
        layout.addRow("Volume", self.volume)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

    def _browse_mirror(self):
        path = QFileDialog.getExistingDirectory(self, "Mirror folder")
        if path:
            self.mirror_edit.setText(path)

    def values(self) -> dict:
        return {
            "theme": self.theme_combo.currentText(),
            "scale": float(self.scale_combo.currentData()),
            "single_focus": self.focus_check.isChecked(),
            "always_on_top": self.always_on_top.isChecked(),
            "snapshot_keep": self.keep_spin.value(),
            "mirror_enabled": self.mirror_check.isChecked(),
            "mirror_dir": self.mirror_edit.text().strip(),
            "sound_enabled": self.sound_check.isChecked(),
            "sound_volume": self.volume.value(),
        }


class SoundDialog(QDialog):
    def __init__(self, library, registry, player, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Sounds")
        self.library = library
        self.registry = registry
        self.player = player
        self.setMinimumSize(520, 460)
        layout = QVBoxLayout(self)

        row = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search sounds...")
        self.search.textChanged.connect(self._filter)
        row.addWidget(self.search, 1)
        layout.addLayout(row)

        self.list_widget = QListWidget()
        self._all = library.all_files()
        self._filter("")
        layout.addWidget(self.list_widget, 1)

        controls = QHBoxLayout()
        self.preview_btn = QPushButton("Preview")
        self.stop_btn = QPushButton("Stop")
        self.preview_btn.clicked.connect(self._preview)
        self.stop_btn.clicked.connect(lambda: player.stop_preview())
        controls.addWidget(self.preview_btn)
        controls.addWidget(self.stop_btn)
        self.volume_slider = QSlider(Qt.Orientation.Horizontal)
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setValue(50)
        controls.addWidget(QLabel("Preview volume"))
        controls.addWidget(self.volume_slider, 1)
        layout.addLayout(controls)

        assign = QHBoxLayout()
        assign.addWidget(QLabel("Assign to event:"))
        self.event_combo = QComboBox()
        self.event_combo.addItems(list(registry.events.keys()))
        assign.addWidget(self.event_combo, 1)
        self.assign_btn = QPushButton("Assign")
        self.assign_btn.clicked.connect(self._assign)
        assign.addWidget(self.assign_btn)
        self.disable_btn = QPushButton("Silence")
        self.disable_btn.clicked.connect(self._disable)
        assign.addWidget(self.disable_btn)
        layout.addLayout(assign)

        self.list_widget.itemDoubleClicked.connect(lambda _i: self._preview())

    def _filter(self, text: str):
        self.list_widget.clear()
        q = text.strip().lower()
        for rel in self._all:
            if q in rel.lower():
                self.list_widget.addItem(QListWidgetItem(rel))
        if self.list_widget.count():
            self.list_widget.setCurrentRow(0)

    def _preview(self):
        item = self.list_widget.currentItem()
        if item is None:
            return
        path = self.library.path_for(item.text())
        if path is not None:
            self.player.preview(path, self.volume_slider.value() / 100.0)

    def _assign(self):
        item = self.list_widget.currentItem()
        if item is None:
            return
        event = self.event_combo.currentText()
        self.registry.set(event, item.text(), enabled=True)
        QMessageBox.information(self, "SAIPLAN", f"{event} -> {item.text()}")

    def _disable(self):
        event = self.event_combo.currentText()
        self.registry.set(event, self.registry.events[event]["file"], enabled=False)
        QMessageBox.information(self, "SAIPLAN", f"{event} silenced (no sound)")


class TimerPanel(QDialog):
    """Stopwatch + Pomodoro + countdown + active ticket timers."""

    def __init__(self, engine, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Timers")
        self.engine = engine
        self.setMinimumSize(380, 300)
        layout = QVBoxLayout(self)
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)

        self.tabs.addTab(self._build_stopwatch(), "Stopwatch")
        self.tabs.addTab(self._build_pomodoro(), "Pomodoro")
        self.tabs.addTab(self._build_countdown(), "Countdown")
        self.tabs.addTab(self._build_ticket(), "Ticket timers")

        self._tick = QTimer(self)
        self._tick.setInterval(500)
        self._tick.timeout.connect(self._refresh)
        self._tick.start()
        self._refresh()

    def _build_stopwatch(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        self.sw_label = QLabel("00:00.0")
        self.sw_label.setObjectName("sectionTitle")
        self.sw_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.sw_label)
        row = QHBoxLayout()
        self.sw_start = QPushButton("Start")
        self.sw_reset = QPushButton("Reset")
        self.sw_start.clicked.connect(self._sw_toggle)
        self.sw_reset.clicked.connect(self.engine.stopwatch.reset)
        row.addWidget(self.sw_start)
        row.addWidget(self.sw_reset)
        layout.addLayout(row)
        layout.addStretch(1)
        return w

    def _build_pomodoro(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        self.pomo_label = QLabel("idle")
        self.pomo_label.setObjectName("sectionTitle")
        self.pomo_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.pomo_label)
        row = QHBoxLayout()
        self.pomo_start = QPushButton("Start work")
        self.pomo_pause = QPushButton("Pause")
        self.pomo_skip = QPushButton("Skip")
        self.pomo_start.clicked.connect(self.engine.pomodoro.start_work)
        self.pomo_pause.clicked.connect(self._pomo_toggle)
        self.pomo_skip.clicked.connect(self.engine.pomodoro.skip)
        row.addWidget(self.pomo_start)
        row.addWidget(self.pomo_pause)
        row.addWidget(self.pomo_skip)
        layout.addLayout(row)
        layout.addStretch(1)
        return w

    def _build_countdown(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        form = QFormLayout()
        self.count_spin = QSpinBox()
        self.count_spin.setRange(1, 600)
        self.count_spin.setValue(5)
        self.count_spin.setSuffix(" min")
        form.addRow("Countdown", self.count_spin)
        layout.addLayout(form)
        row = QHBoxLayout()
        self.count_start = QPushButton("Start")
        self.count_start.clicked.connect(self._countdown_start)
        row.addWidget(self.count_start)
        layout.addLayout(row)
        self.count_label = QLabel("")
        layout.addWidget(self.count_label)
        self.deadline_list = QListWidget()
        layout.addWidget(self.deadline_list, 1)
        buttons = QHBoxLayout()
        self.deadline_cancel = QPushButton("Cancel selected")
        self.deadline_snooze = QPushButton("Snooze 5 min")
        self.deadline_cancel.clicked.connect(self._deadline_cancel)
        self.deadline_snooze.clicked.connect(self._deadline_snooze)
        buttons.addWidget(self.deadline_cancel)
        buttons.addWidget(self.deadline_snooze)
        layout.addLayout(buttons)
        return w

    def _build_ticket(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        self.ticket_list = QListWidget()
        layout.addWidget(self.ticket_list, 1)
        row = QHBoxLayout()
        self.ticket_stop = QPushButton("Stop selected")
        self.ticket_stop.clicked.connect(self._ticket_stop)
        row.addWidget(self.ticket_stop)
        layout.addLayout(row)
        return w

    def _sw_toggle(self):
        if self.engine.stopwatch.running:
            self.engine.stopwatch.pause()
        else:
            self.engine.stopwatch.resume()

    def _pomo_toggle(self):
        p = self.engine.pomodoro
        if p._paused_at is not None:
            p.resume()
        elif p.running:
            p.pause()
        else:
            p.start_work()

    def _countdown_start(self):
        mins = self.count_spin.value()
        from datetime import datetime

        target = datetime.fromtimestamp(time.time() + mins * 60, tz=UTC).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        self.engine.add_deadline(target, label=f"countdown {mins} min")
        self.count_label.setText("active")

    def _deadline_cancel(self):
        item = self.deadline_list.currentItem()
        if item is not None:
            tid = item.data(Qt.ItemDataRole.UserRole)
            if tid:
                self.engine.cancel(tid)

    def _deadline_snooze(self):
        item = self.deadline_list.currentItem()
        if item is not None:
            tid = item.data(Qt.ItemDataRole.UserRole)
            if tid:
                self.engine.snooze(tid, 300)

    def _ticket_stop(self):
        item = self.ticket_list.currentItem()
        if item is None:
            return
        ticket_id = item.data(Qt.ItemDataRole.UserRole)
        if ticket_id and self.engine.ticket_timer:
            self.engine.ticket_timer.stop_ticket(ticket_id)

    def _refresh(self):
        sw = self.engine.stopwatch.elapsed()
        self.sw_label.setText(self._fmt(sw, ms=True))
        self.sw_start.setText("Pause" if self.engine.stopwatch.running else "Start")
        p = self.engine.pomodoro
        if p.phase == "idle":
            self.pomo_label.setText("idle")
            self.pomo_pause.setEnabled(False)
            self.pomo_pause.setText("Pause")
        else:
            self.pomo_label.setText(f"{p.phase}  {self._fmt(p.phase_remaining())}")
            self.pomo_pause.setEnabled(True)
            self.pomo_pause.setText("Resume" if p._paused_at is not None else "Pause")
        # active deadlines with live remaining time + cancel/snooze
        self.deadline_list.clear()
        now = time.time()
        for timer in self.engine.deadline.values():
            remaining = parse_iso(timer.target_at) - now
            text = (
                f"{timer.label}  {self._fmt(remaining)}" if remaining is not None else timer.label
            )
            item = QListWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole, timer.tid)
            self.deadline_list.addItem(item)
        if self.deadline_list.count():
            self.count_label.setText(f"{self.deadline_list.count()} active")
        else:
            self.count_label.setText("no active countdowns")
        self.ticket_list.clear()
        tt = getattr(self.engine, "ticket_timer", None)
        if tt is not None:
            for tid in tt.running():
                item = QListWidgetItem(f"{tid}  since {tt.started_at(tid)}")
                item.setData(Qt.ItemDataRole.UserRole, tid)
                self.ticket_list.addItem(item)

    @staticmethod
    def _fmt(seconds: float, ms: bool = False) -> str:
        seconds = max(0.0, float(seconds))
        whole = int(seconds)
        h, rem = divmod(whole, 3600)
        m, s = divmod(rem, 60)
        if ms:
            tenth = int((seconds - whole) * 10)
            return f"{h:02d}:{m:02d}:{s:02d}.{tenth}"
        return f"{h:02d}:{m:02d}:{s:02d}"


class TrashDialog(QDialog):
    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Trash")
        self.controller = controller
        self.setMinimumSize(460, 320)
        layout = QVBoxLayout(self)
        self.list_widget = QListWidget()
        layout.addWidget(self.list_widget, 1)
        row = QHBoxLayout()
        self.restore_btn = QPushButton("Restore to TODO")
        self.restore_btn.clicked.connect(self._restore)
        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        row.addWidget(self.restore_btn)
        row.addWidget(close)
        layout.addLayout(row)
        self._refresh()

    def _refresh(self):
        from ..core.history import Trash

        self.list_widget.clear()
        for rec in Trash(self.controller.plan.trash_path.parent).list(self.controller.plan.plan_id):
            item = QListWidgetItem(f"{rec['ticket_id']}  {rec['title']}")
            item.setData(Qt.ItemDataRole.UserRole, rec["ticket_id"])
            self.list_widget.addItem(item)

    def _restore(self):
        item = self.list_widget.currentItem()
        if item is None:
            return
        tid = item.data(Qt.ItemDataRole.UserRole)
        try:
            self.controller.restore_ticket(tid)
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(self, "SAIPLAN", str(e))
            return
        self._refresh()
        self.board_changed = True


class ReviewDialog(QDialog):
    def __init__(self, findings, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Plan Review")
        self.setMinimumSize(480, 360)
        layout = QVBoxLayout(self)
        self.list_widget = QListWidget()
        if not findings:
            self.list_widget.addItem("No warnings. The plan is clear.")
        for severity, ticket_id, message in findings:
            tag = "warn" if severity == "warn" else "note"
            item = QListWidgetItem(f"[{tag}] {ticket_id or '-'}  {message}")
            self.list_widget.addItem(item)
        layout.addWidget(self.list_widget, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)


class StatsDialog(QDialog):
    """A few honest numbers from the plain files. No charts."""

    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Statistics")
        self.setMinimumWidth(360)
        layout = QVBoxLayout(self)
        from ..extras import statistics as stats

        counts = controller.board.counts()
        lines = [
            f"DOING      {counts['DOING']}",
            f"TODO       {counts['TODO']}",
            f"DONE       {counts['DONE']}",
            f"BLOCKED    {counts['BLOCKED']}",
            f"Tracked time   {self._fmt_time(stats.total_time(controller.plan))}",
            f"Completed today     {stats.completed_today(controller.plan)}",
            f"Completed (7 days)  {stats.completed_last_days(controller.plan)}",
        ]
        activity = stats.activity_counts(controller.plan)
        for event, count in sorted(activity.items()):
            lines.append(f"{event:<16} {count}")
        label = QLabel("\n".join(lines))
        label.setObjectName("sectionTitle")
        label.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(label)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)

    @staticmethod
    def _fmt_time(seconds: float) -> str:
        h, rem = divmod(int(seconds), 3600)
        m = rem // 60
        if h:
            return f"{h}h {m}m"
        return f"{m}m"


class ConflictDialog(QDialog):
    """External edit detected: reload, keep mine (conflict copy), or cancel."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("BOARD.md changed externally")
        layout = QVBoxLayout(self)
        layout.addWidget(
            QLabel(
                "BOARD.md was modified outside SAIPLAN.\n"
                "SAIPLAN never silently overwrites external edits."
            )
        )
        buttons = QDialogButtonBox()
        reload_btn = buttons.addButton(
            "Reload external version", QDialogButtonBox.ButtonRole.AcceptRole
        )
        keep_btn = buttons.addButton(
            "Keep my version (conflict copy)", QDialogButtonBox.ButtonRole.ActionRole
        )
        cancel_btn = buttons.addButton("Cancel", QDialogButtonBox.ButtonRole.RejectRole)
        reload_btn.clicked.connect(lambda: self.done(1))
        keep_btn.clicked.connect(lambda: self.done(2))
        cancel_btn.clicked.connect(self.reject)
        layout.addWidget(buttons)


class RecoveryDialog(QDialog):
    """Browse .history recovery artifacts and restore a validated snapshot.

    Restore is transactional on the controller side: the current primary is
    backed up byte-exact first (restore-before copy), an undo entry is
    recorded, `SNAPSHOT_RESTORED` is appended to the semantic LOG, and the
    snapshot is adopted only after the save lands. The dialog itself never
    mutates the board — it asks the controller, one writer (spec 2).
    """

    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.controller = controller
        self.artifacts = controller.recovery_artifacts()
        self._items: list[dict] = []
        self.setWindowTitle("Recovery")
        self.setMinimumSize(680, 460)
        layout = QVBoxLayout(self)
        hint = QLabel(
            "Snapshots are automatic backups of BOARD.md, created on every save. "
            "Restore puts a validated snapshot back in place — your current board "
            "is backed up first, and undo still works. Forensic corrupt and "
            "pre-restore copies are kept byte-exact for inspection."
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)

        split = QHBoxLayout()
        self.list_widget = QListWidget()
        self.list_widget.currentRowChanged.connect(self._on_select)
        split.addWidget(self.list_widget, 1)
        self.preview = QPlainTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setPlaceholderText("Select an artifact to preview its contents.")
        split.addWidget(self.preview, 2)
        layout.addLayout(split, 1)

        buttons = QDialogButtonBox()
        self.restore_btn = buttons.addButton(
            "Restore selected snapshot", QDialogButtonBox.ButtonRole.AcceptRole
        )
        close_btn = buttons.addButton("Close", QDialogButtonBox.ButtonRole.RejectRole)
        self.restore_btn.clicked.connect(self._restore)
        close_btn.clicked.connect(self.reject)
        layout.addWidget(buttons)

        self._populate()

    # -- listing ------------------------------------------------------
    def _populate(self) -> None:
        self.list_widget.clear()
        self._items = list(self.artifacts)
        for artifact in self._items:
            item = QListWidgetItem(self._label(artifact))
            item.setData(Qt.ItemDataRole.UserRole, artifact["path"])
            if artifact["kind"] != "snapshot" or not artifact["valid"]:
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEnabled)
            self.list_widget.addItem(item)
        if not self._items:
            self.list_widget.addItem("No recovery artifacts yet. Snapshots appear on every save.")
        self.list_widget.setCurrentRow(0)

    @staticmethod
    def _label(artifact: dict) -> str:
        ts = datetime.datetime.fromtimestamp(artifact["mtime_ns"] / 1e9, tz=UTC).strftime(
            "%Y-%m-%d %H:%M"
        )
        kind = artifact["kind"]
        tag = {
            "snapshot": "snapshot",
            "corrupt": "corrupt primary copy",
            "restore-before": "pre-restore backup",
        }[kind]
        suffix = "" if (kind == "snapshot" and artifact["valid"]) else " (view only)"
        return f"{ts}  [{tag}]{suffix}  {artifact['summary']}"

    def _on_select(self, row: int) -> None:
        if row < 0 or row >= len(self._items):
            self.preview.setPlainText("")
            self.restore_btn.setEnabled(False)
            return
        artifact = self._items[row]
        try:
            text = Path(artifact["path"]).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            text = ""
        self.preview.setPlainText(text)
        self.restore_btn.setEnabled(artifact["kind"] == "snapshot" and artifact["valid"])

    def _restore(self) -> None:
        row = self.list_widget.currentRow()
        if row < 0 or row >= len(self._items):
            return
        artifact = self._items[row]
        answer = QMessageBox.question(
            self,
            "Restore snapshot?",
            "This replaces the current BOARD.md with the selected snapshot.\n"
            "The current board is backed up first and undo stays available.",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            self.controller.restore_snapshot(artifact["path"])
        except Exception as exc:  # noqa: BLE001 - surface any refusal to the human
            QMessageBox.warning(self, "Restore refused", str(exc))
            return
        self.artifacts = self.controller.recovery_artifacts()
        self._populate()
        QMessageBox.information(
            self,
            "Snapshot restored",
            "The snapshot is now BOARD.md. A backup of the previous board and "
            "an undo entry were kept.",
        )
