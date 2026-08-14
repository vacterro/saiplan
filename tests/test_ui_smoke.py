"""UI smoke tests (spec 19). Run headless with QT_QPA_PLATFORM=offscreen.

Cover the definition-of-done flow: launch -> create plan -> add ticket ->
TODO -> DOING -> DONE -> restart -> state correct.
"""

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PyQt6")
pytestmark = pytest.mark.qt

from PyQt6.QtWidgets import QApplication

from saiplan.core.config import Config
from saiplan.core.model import DOING, DONE, TODO
from saiplan.core.persistence import BoardStore
from saiplan.extras.timers import TimerEngine
from saiplan.theme.registry import ThemeRegistry
from saiplan.ui.controller import BoardController
from saiplan.ui.shell import App, MainWindow


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def app_ctx(tmp_path, qapp):
    root = tmp_path / "SAIPLAN"
    layout = {
        "root": root,
        "data": root / "data",
        "plans": root / "data" / "plans",
        "config": root / "data" / "config.json",
        "themes": Path(__file__).resolve().parents[1] / "themes",
        "sounds": Path(__file__).resolve().parents[1] / "sounds",
        "logs": root / "logs",
    }
    for p in layout.values():
        if str(p).endswith(".json"):
            p.parent.mkdir(parents=True, exist_ok=True)
        else:
            p.mkdir(parents=True, exist_ok=True)
    config = Config(layout["config"])
    config.load()
    engine = TimerEngine(layout["data"] / "timers.jsonl")
    ctx = App(layout, config, ThemeRegistry(layout["themes"]), engine)
    # a plan must exist before MainWindow is built: the first-run path opens a
    # modal dialog that would block headless tests
    ctx.plan_store.create("Seed Plan")
    return ctx


def _window(app_ctx):
    win = MainWindow(app_ctx)
    win.show()
    return win


def test_create_plan_then_ticket_flow(app_ctx):
    win = _window(app_ctx)
    plan = app_ctx.plan_store.create("Smoke Plan", "Ship the thing")
    win._open_plan(plan)
    controller = app_ctx.controller
    # quick-add path (what a fresh user types)
    ticket = controller.create_ticket("Buy and install new SSD")
    assert ticket.status == TODO
    win._refresh()
    # the ticket is rendered in the TODO column
    col = win.board_view.columns[TODO]
    titles = [col.item(i).text() for i in range(col.count())]
    assert any("Buy and install new SSD" in t for t in titles)
    # TODO -> DOING -> DONE through the UI action path
    win._on_drop(ticket.ticket_id, DOING)
    assert app_ctx.controller.board.get(ticket.ticket_id).status == DOING
    win._on_drop(ticket.ticket_id, DONE)
    assert app_ctx.controller.board.get(ticket.ticket_id).status == DONE
    win._refresh()
    assert win.board_view.columns[DONE].count() == 1
    win.close()


def test_restart_state_correct(app_ctx):
    """Violent close simulation: reopen the controller from disk."""
    win = _window(app_ctx)
    plan = app_ctx.plan_store.create("Restart Plan")
    win._open_plan(plan)
    t = app_ctx.controller.create_ticket("Do the thing")
    win._on_drop(t.ticket_id, DOING)
    win.close()

    # restart: new controller, same files
    store = BoardStore(plan.board_path, plan.history_dir)
    c2 = BoardController(plan, store, app_ctx.config)
    c2.load()
    t2 = c2.board.get(t.ticket_id)
    assert t2 is not None
    assert t2.status == DOING
    assert t2.title == "Do the thing"


def test_undo_redo_across_restart(app_ctx):
    win = _window(app_ctx)
    plan = app_ctx.plan_store.create("Undo Plan")
    win._open_plan(plan)
    c = app_ctx.controller
    c.create_ticket("First")
    t2 = c.create_ticket("Second")
    assert c.board.get(t2.ticket_id) is not None
    assert c.undo()
    assert c.board.get(t2.ticket_id) is None
    assert c.redo()
    assert c.board.get(t2.ticket_id) is not None
    win.close()


def test_inspector_shows_selected_ticket(app_ctx):
    win = _window(app_ctx)
    plan = app_ctx.plan_store.create("Inspector Plan")
    win._open_plan(plan)
    t = app_ctx.controller.create_ticket("Inspect me")
    win._on_activate(t.ticket_id)
    assert win.inspector.ticket_id == t.ticket_id
    assert win.inspector.title_edit.text() == "Inspect me"
    win.close()


def test_details_flush_before_fast_ticket_switch(app_ctx):
    win = _window(app_ctx)
    plan = app_ctx.plan_store.create("Draft switch")
    win._open_plan(plan)
    first = app_ctx.controller.create_ticket("First")
    second = app_ctx.controller.create_ticket("Second")
    win._on_activate(first.ticket_id)
    win.inspector.details_edit.setPlainText("draft survives")
    win._on_activate(second.ticket_id)
    assert app_ctx.controller.board.get(first.ticket_id).get("details") == "draft survives"
    assert win.inspector.ticket_id == second.ticket_id
    win.close()


def test_failed_details_save_preserves_visible_dirty_draft(app_ctx, monkeypatch):
    win = _window(app_ctx)
    plan = app_ctx.plan_store.create("Draft failure")
    win._open_plan(plan)
    first = app_ctx.controller.create_ticket("First")
    second = app_ctx.controller.create_ticket("Second")
    win._on_activate(first.ticket_id)
    win.inspector.details_edit.setPlainText("must remain visible")

    def fail(*_args, **_kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(app_ctx.controller, "edit_field", fail)
    win._on_activate(second.ticket_id)
    assert win.inspector.ticket_id == first.ticket_id
    assert win.inspector.details_edit.toPlainText() == "must remain visible"
    assert "Unsaved changes" in win.inspector.unsaved_label.text()
    monkeypatch.undo()
    assert win.inspector.flush_pending()
    win.close()


def test_programmatic_ticket_refresh_does_not_create_details_draft(app_ctx):
    win = _window(app_ctx)
    plan = app_ctx.plan_store.create("No phantom draft")
    win._open_plan(plan)
    ticket = app_ctx.controller.create_ticket("Ticket")
    win._on_activate(ticket.ticket_id)
    win._refresh()
    assert win.inspector._dirty_ticket_id is None
    assert win.inspector.unsaved_label.text() == ""
    win.close()


def test_trash_and_restore_ui(app_ctx):
    win = _window(app_ctx)
    plan = app_ctx.plan_store.create("Trash Plan")
    win._open_plan(plan)
    t = app_ctx.controller.create_ticket("Trash me later")
    app_ctx.controller.delete_ticket(t.ticket_id)
    assert app_ctx.controller.board.get(t.ticket_id) is None
    app_ctx.controller.restore_ticket(t.ticket_id)
    assert app_ctx.controller.board.get(t.ticket_id) is not None
    win.close()


def test_export_plan_handler_writes_bundle(app_ctx, monkeypatch):
    win = _window(app_ctx)
    plan = app_ctx.plan_store.create("Portable Plan")
    win._open_plan(plan)
    win._load_plans()  # the export action resolves plan_id against the list
    app_ctx.controller.create_ticket("Alpha")
    bundle = app_ctx.layout["data"] / "portable.saiplan"
    monkeypatch.setattr(
        "PyQt6.QtWidgets.QFileDialog.getSaveFileName",
        lambda *a, **k: (str(bundle), "SAIPLAN bundle (*.saiplan)"),
    )
    win._export_plan(plan.plan_id)
    assert bundle.is_file()
    from saiplan.core.bundle import import_plan

    # the original id is taken here (never clobbers) — import into a fresh root
    fresh_root = app_ctx.layout["data"] / "plans-imported"
    imported = import_plan(fresh_root, bundle)
    assert imported.plan_id == plan.plan_id
    win.close()


def test_import_plan_handler_opens_imported_plan(app_ctx, monkeypatch):
    win = _window(app_ctx)
    plan = app_ctx.plan_store.create("Importable")
    bundle = app_ctx.layout["data"] / "importable.saiplan"
    from saiplan.core.bundle import export_plan

    export_plan(plan, bundle)
    import shutil

    shutil.rmtree(plan.directory)  # id must be free for import (never clobbers)
    monkeypatch.setattr(
        "PyQt6.QtWidgets.QFileDialog.getOpenFileName",
        lambda *a, **k: (str(bundle), "SAIPLAN bundle (*.saiplan)"),
    )
    win._import_plan()
    assert app_ctx.controller.plan.plan_id == plan.plan_id
    win.close()


def test_recovery_dialog_lists_and_previews(app_ctx):
    win = _window(app_ctx)
    plan = app_ctx.plan_store.create("Recovery Plan")
    win._open_plan(plan)
    controller = app_ctx.controller
    controller.create_ticket("Alpha")
    controller.create_ticket("Beta")
    from saiplan.ui.dialogs import RecoveryDialog

    dialog = RecoveryDialog(controller)
    assert dialog.list_widget.count() >= 1
    # newest artifact is a valid snapshot: preview populated, restore enabled
    dialog.list_widget.setCurrentRow(0)
    assert dialog.preview.toPlainText()
    assert dialog.restore_btn.isEnabled()
    # a forensic corrupt copy appears and is view-only (restore disabled)
    controller.store.preserve_raw_corrupt(b"\xff\xfe raw corrupt")
    dialog.artifacts = controller.recovery_artifacts()
    dialog._populate()
    assert dialog.list_widget.count() >= 2
    dialog.list_widget.setCurrentRow(0)  # newest artifact is the corrupt copy
    assert not dialog.restore_btn.isEnabled()
    # selecting a valid snapshot re-enables restore
    dialog.list_widget.setCurrentRow(1)
    assert dialog.restore_btn.isEnabled()
    # view-only rows are disabled (flags cleared, not a QWidget)
    from PyQt6.QtCore import Qt as _Qt

    assert not (dialog.list_widget.item(0).flags() & _Qt.ItemFlag.ItemIsEnabled)
    dialog.deleteLater()
    win.close()


def test_break_down_wizard_creates_tickets(app_ctx):
    win = _window(app_ctx)
    plan = app_ctx.plan_store.create("Breakdown Plan")
    win._open_plan(plan)
    controller = app_ctx.controller
    from saiplan.ui.dialogs import BreakDownDialog

    dialog = BreakDownDialog()
    dialog.goal.setPlainText("Install new SSD")
    dialog.tasks.setPlainText("Buy SSD\nInstall :: needs=S-1")
    assert dialog.plan()["tasks"] == ["Buy SSD", "Install :: needs=S-1"]
    # emulate the shell handler
    for line in dialog.plan()["tasks"]:
        title, _, _ = line.partition("::")
        controller.create_ticket(title.strip())
    assert controller.board.counts()[TODO] == 2
    win.close()


def test_theme_switching_at_runtime(app_ctx, qapp):
    win = _window(app_ctx)
    before = qapp.styleSheet()
    app_ctx.config.set("theme", "vintageclassic")
    win._apply_theme()
    after = qapp.styleSheet()
    assert before != after
    assert "backgroundSoft" not in after  # resolved QSS
    win.close()


def _quick_add(win):
    return win.board_view.quick_add


def test_quick_add_enter_creates_visible_todo(app_ctx):
    """REAL QuickAdd interaction: type + Enter -> ticket visible in TODO
    immediately (not by calling controller directly)."""
    win = _window(app_ctx)
    qa = _quick_add(win)
    qa.setFocus()
    qa.setText("Buy and install new SSD")
    qa.returnPressed.emit()
    # controller state
    assert any(t.title == "Buy and install new SSD" for t in app_ctx.controller.board.all_tickets())
    # rendered in the TODO column
    col = win.board_view.columns[TODO]
    titles = [col.item(i).text() for i in range(col.count())]
    assert any("Buy and install new SSD" in t for t in titles)
    # input cleared on success
    assert qa.text() == ""
    win.close()


def test_quick_add_failure_keeps_typed_text(app_ctx):
    win = _window(app_ctx)
    qa = _quick_add(win)
    # force a failure: readonly controller refuses mutations
    app_ctx.controller._readonly = True
    qa.setText("This must survive")
    qa.returnPressed.emit()
    assert qa.text() == "This must survive"
    assert not any(t.title == "This must survive" for t in app_ctx.controller.board.all_tickets())
    app_ctx.controller._readonly = False
    win.close()


def test_inspector_start_button_refreshes_board(app_ctx):
    win = _window(app_ctx)
    plan = app_ctx.plan_store.create("Inspector Start Plan")
    win._open_plan(plan)
    t = app_ctx.controller.create_ticket("Ready to start")
    win._on_activate(t.ticket_id)
    assert win.inspector.ticket_id == t.ticket_id
    win.inspector.btn_start.click()
    # model moved
    assert app_ctx.controller.board.get(t.ticket_id).status == DOING
    # board column refreshed
    win._refresh()
    assert win.board_view.columns[DOING].count() == 1
    win.close()


def test_inspector_done_refreshes_and_fires_event(app_ctx):
    win = _window(app_ctx)
    plan = app_ctx.plan_store.create("Inspector Done Plan")
    win._open_plan(plan)
    t = app_ctx.controller.create_ticket("Finish me")
    win._on_drop(t.ticket_id, DOING)
    win._on_activate(t.ticket_id)
    win.inspector.btn_done.click()
    assert app_ctx.controller.board.get(t.ticket_id).status == DONE
    # the board_changed signal refreshed the DONE column
    assert win.board_view.columns[DONE].count() == 1
    win.close()


def test_inspector_delete_refreshes_board(app_ctx):
    win = _window(app_ctx)
    plan = app_ctx.plan_store.create("Inspector Delete Plan")
    win._open_plan(plan)
    t = app_ctx.controller.create_ticket("Delete me")
    win._on_activate(t.ticket_id)
    win.inspector.controller.delete_ticket(t.ticket_id)
    win.inspector.set_ticket(None)
    win.inspector.board_changed.emit()
    win._refresh()
    assert app_ctx.controller.board.get(t.ticket_id) is None
    assert win.board_view.columns[TODO].count() == 0
    win.close()


def test_priority_combo_single_control_and_persists(app_ctx):
    """Priority is a single QComboBox (not also a QLineEdit) and saves."""
    win = _window(app_ctx)
    plan = app_ctx.plan_store.create("Priority Plan")
    win._open_plan(plan)
    t = app_ctx.controller.create_ticket("Prioritised")
    win._on_activate(t.ticket_id)
    assert "priority" not in win.inspector.field_edits  # no duplicate control
    win.inspector.priority_combo.setCurrentText("high")
    win.inspector._save_priority()
    assert app_ctx.controller.board.get(t.ticket_id).get("priority") == "high"
    # survives reload
    from saiplan.core.persistence import BoardStore
    from saiplan.ui.controller import BoardController

    c2 = BoardController(plan, BoardStore(plan.board_path, plan.history_dir))
    c2.load()
    assert c2.board.get(t.ticket_id).get("priority") == "high"
    win.close()


def test_checklist_field_is_in_contract():
    from saiplan.core.model import KNOWN_FIELDS

    assert "checklist" in KNOWN_FIELDS


def test_pomodoro_pause_resume_toggle(app_ctx):
    from saiplan.ui.dialogs import TimerPanel

    panel = TimerPanel(app_ctx.timer_engine)
    p = app_ctx.timer_engine.pomodoro
    panel._pomo_toggle()  # idle -> work
    assert p.phase == "work"
    panel._pomo_toggle()  # running -> paused
    assert p._paused_at is not None
    panel._refresh()
    assert panel.pomo_pause.text() == "Resume"
    panel._pomo_toggle()  # paused -> resume
    assert p._paused_at is None
    panel._refresh()
    assert panel.pomo_pause.text() == "Pause"
    panel.close()


def test_archive_active_plan_detaches_controller(app_ctx):
    """Archiving the active plan must detach the controller so a later
    mutation cannot recreate the archived directory path."""
    from saiplan.extras import archive

    win = _window(app_ctx)
    plan = app_ctx.plan_store.create("To Archive")
    win._open_plan(plan)
    win._detach_active_plan()
    assert app_ctx.controller is None
    archived = archive.archive_plan(app_ctx.layout["plans"], plan.plan_id)
    assert archived is not None
    assert not (app_ctx.layout["plans"] / plan.plan_id).exists()
    # nothing left that could recreate the old path
    assert app_ctx.controller is None and app_ctx.ticket_timer is None
    assert not (app_ctx.layout["plans"] / plan.plan_id).exists()
    win.close()


def test_two_sequential_conflicts_both_surface(app_ctx):
    """_conflict_shown must re-arm after resolution so a second external edit
    in the same open plan shows the banner again."""
    from saiplan.core.board import render_board
    from saiplan.core.persistence import atomic_write

    win = _window(app_ctx)
    plan = app_ctx.plan_store.create("Conflict Plan")
    win._open_plan(plan)
    c = app_ctx.controller
    c.create_ticket("Base")

    def _external_edit():
        atomic_write(
            plan.board_path,
            render_board(c.board).replace("## BLOCKED", "- [ ] S-999 External\n## BLOCKED"),
        )

    _external_edit()
    win._poll_external()
    assert win._conflict_shown is True
    # emulate the user resolving with keep-mine (bypasses the modal dialog)
    win._conflict_shown = False
    c.resolve_keep_mine()
    win._poll_external()
    assert win._conflict_shown is False  # re-armed

    _external_edit()
    win._poll_external()
    assert win._conflict_shown is True  # second conflict surfaces
    win.close()


def test_extras_disabled_board_still_opens(tmp_path, qapp):
    """I8/I1: broken extras must not prevent the board from opening."""
    from saiplan.theme.registry import ThemeRegistry
    from saiplan.ui.shell import App

    root = tmp_path / "SAIPLAN"
    layout = {
        "root": root,
        "data": root / "data",
        "plans": root / "data" / "plans",
        "config": root / "data" / "config.json",
        "themes": root / "missing-themes",  # no theme files at all
        "sounds": root / "missing-sounds",  # no sounds at all
        "logs": root / "logs",
    }
    for p in layout.values():
        if str(p).endswith(".json"):
            p.parent.mkdir(parents=True, exist_ok=True)
        else:
            p.mkdir(parents=True, exist_ok=True)
    config = Config(layout["config"])
    config.load()
    engine = TimerEngine(layout["data"] / "timers.jsonl")
    ctx = App(layout, config, ThemeRegistry(layout["themes"]), engine)
    ctx.plan_store.create("Core Plan")
    win = MainWindow(ctx)  # must not raise despite broken extras
    win.show()
    assert ctx.controller is not None
    # board still fully usable: create + move a ticket
    t = ctx.controller.create_ticket("Core works")
    win._on_drop(t.ticket_id, DOING)
    assert ctx.controller.board.get(t.ticket_id).status == DOING
    assert ctx.sound_library.count() == 0
    win.close()
