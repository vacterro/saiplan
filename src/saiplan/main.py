"""SAIPLAN entry point.

Order: logging -> portable layout -> single instance -> config -> theme ->
window. A failure in any extra (theme, sounds, timers) is contained; the
board still opens (I8). If the data dir is read-only the app fails loudly
and offers an alternate writable location instead of scattering data.
"""

from __future__ import annotations

import logging
import os
import sys
import time

from .applog import setup_logging
from .core.config import Config
from .extras.timers import TimerEngine
from .platform import paths
from .platform.single_instance import (
    SingleInstanceMutex,
    handoff_available,
    new_token,
    notify_existing_instance,
    write_nonce,
)
from .theme.registry import ThemeRegistry

logger = logging.getLogger("saiplan")

_ACK_BYTES = b"ACK\n"
STARTUP_GRACE_S = 2.5


def _handoff_to_first(layout: dict) -> bool:
    """Ask the running first instance to activate its window. Returns True
    when its ACK was received (this process should then exit)."""
    if not handoff_available():
        return False
    deadline = time.monotonic() + STARTUP_GRACE_S
    while time.monotonic() < deadline:
        try:
            if notify_existing_instance("Saiplan", layout, timeout_ms=600):
                return True
        except Exception as e:  # noqa: BLE001
            logger.warning("single-instance handoff attempt failed: %s", e)
        time.sleep(0.15)
    return False


def main() -> int:
    layout = paths.resolve_layout()
    ok, message = paths.layout_status(layout)
    if not ok:
        print(message, file=sys.stderr)
        # loud refusal on a read-only install — no silent data scatter
        return 2
    paths.ensure_layout_dirs(layout)
    logger = setup_logging(layout["logs"])
    logger.info("SAIPLAN starting; root=%s", layout["root"])

    from PyQt6.QtNetwork import QLocalServer
    from PyQt6.QtWidgets import QApplication, QMessageBox

    app = QApplication(sys.argv)
    app.setApplicationName("SAIPLAN")
    app.setOrganizationName("saiplan")

    # SINGLE WRITER GATE (mutex is authority): a process that does not own the
    # mutex must NEVER become a writer to the shared BOARD. It attempts the
    # handoff during a bounded grace window, then exits either way.
    mutex = SingleInstanceMutex("Saiplan")
    if not mutex.is_first:
        activated = _handoff_to_first(layout)
        logger.info("second instance; handoff %s; exiting", "ACK" if activated else "refused")
        mutex.release()
        if activated:
            return 0
        print(
            "SAIPLAN is already running. A second instance is refused — "
            "one writer per plan. Exiting.",
            file=sys.stderr,
        )
        return 1
    # mutex held: this process is the writer. It lives for the whole main().

    # CI/smoke hook: auto-quit after a fixed delay. Implemented as a repeating
    # watchdog so it also fires while a modal dialog's nested event loop runs
    # (first-run Create Plan) — closeAllWindows rejects the dialog, then quit
    # ends the app.
    autoquit = os.environ.get("SAIPLAN_AUTOQUIT_MS")
    if autoquit and autoquit.isdigit():
        from PyQt6.QtCore import QTimer

        deadline = time.monotonic() + max(0.2, int(autoquit) / 1000.0)

        def _maybe_quit():
            if time.monotonic() >= deadline:
                # close every widget (modal dialogs with parents are not in
                # topLevelWidgets) — closing a QDialog rejects its exec loop
                for widget in list(app.allWidgets()):
                    try:
                        widget.close()
                    except Exception as e:  # noqa: BLE001  (isolation by design)
                        logger.debug("autoquit close failed: %s", e)
                app.quit()
                # keep re-arming: quit() during a modal nested loop only
                # rejects that dialog; the real app.exec() may start later
                QTimer.singleShot(500, _maybe_quit)
            else:
                QTimer.singleShot(200, _maybe_quit)

        QTimer.singleShot(200, _maybe_quit)

    config = Config(layout["config"])
    config.load()

    from .ui.shell import App, MainWindow

    # extras that must never block the board (I8)
    try:
        theme_registry = ThemeRegistry(layout["themes"])
    except Exception as e:  # noqa: BLE001
        logger.error("theme registry failed: %s", e)
        theme_registry = None
    timer_engine = TimerEngine(layout["data"] / "timers.jsonl")

    app_ctx = App(layout, config, theme_registry, timer_engine)

    handoff_nonce = new_token()
    write_nonce(layout, handoff_nonce)
    server = QLocalServer(app)
    server.removeServer("Saiplan")
    server.listen("Saiplan")
    window = None

    def _on_connection():
        conn = server.nextPendingConnection()
        if conn is None:
            return
        conn.waitForReadyRead(2000)
        data = bytes(conn.readAll())
        if data == handoff_nonce.encode():
            conn.write(_ACK_BYTES)
            conn.flush()
            if window is not None:
                window.raise_()
                window.activateWindow()
        conn.disconnectFromServer()
        conn.deleteLater()

    server.newConnection.connect(_on_connection)

    try:
        window = MainWindow(app_ctx)
    except Exception as e:
        logger.critical("window failed to build: %s", e, exc_info=True)
        QMessageBox.critical(None, "SAIPLAN", f"SAIPLAN could not start:\n{e}")
        mutex.release()
        return 1

    window.show()
    rc = app.exec()
    app_ctx.timer_engine.save()
    mutex.release()
    logger.info("SAIPLAN exit rc=%s", rc)
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
