"""UI smoke tests (spec 19). Run headless with QT_QPA_PLATFORM=offscreen.

Cover the definition-of-done flow: launch -> create plan -> add ticket ->
TODO -> DOING -> DONE -> restart -> state correct.
"""

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PyQt6")

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
