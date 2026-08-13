"""Single instance: Windows named mutex (authority) + token IPC handoff.

Model from the audited FastPrompter: the mutex is the source of truth on
"someone is running"; the IPC handoff exists only to tell that instance to
show its window. A second instance that cannot reach the first exits — it
never becomes a second writer to the same plan.
"""

from __future__ import annotations

import ctypes
import secrets
import sys

ERROR_ALREADY_EXISTS = 183
kernel32 = None

if sys.platform == "win32":
    kernel32 = ctypes.windll.kernel32


class SingleInstanceMutex:
    """Session-scoped named mutex held for the process lifetime.

    `is_first` is True for the process that acquired the mutex fresh. Release
    it explicitly on clean exit; a hard kill releases it automatically
    (kernel-owned object, not a lock file).
    """

    def __init__(self, name: str = "Saiplan"):
        self.name = name
        self._handle = None
        self.is_first = True
        if kernel32 is not None:
            self._handle = kernel32.CreateMutexW(None, False, f"Local\\{name}")
            err = kernel32.GetLastError()
            self.is_first = err != ERROR_ALREADY_EXISTS
        else:
            self.is_first = True

    def release(self) -> None:
        if self._handle is not None:
            kernel32.CloseHandle(self._handle)
            self._handle = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.release()
        return False


def new_token() -> str:
    """Random token authenticating a handoff (never guessable, never stored)."""
    return secrets.token_urlsafe(24)


def handoff_available() -> bool:
    """Qt is required for QLocalServer/QLocalSocket handoff."""
    try:
        from PyQt6.QtNetwork import QLocalServer, QLocalSocket  # noqa: F401

        return True
    except Exception:  # noqa: BLE001
        return False


def notify_existing_instance(server_name: str, token: str, timeout_ms: int = 2000) -> bool:
    """Ask the running instance (listening on `server_name`) to activate.

    Returns True when the handoff was delivered. Bounded by a timer so a dead
    server never hangs the second instance.
    """
    from PyQt6.QtCore import QEventLoop, QTimer
    from PyQt6.QtNetwork import QLocalSocket

    socket = QLocalSocket()
    loop = QEventLoop()
    delivered = [False]

    def _connected():
        socket.write(token.encode("utf-8"))
        socket.flush()
        delivered[0] = True
        loop.quit()

    socket.connected.connect(_connected)
    socket.errorOccurred.connect(lambda _e: loop.quit())
    QTimer.singleShot(timeout_ms, loop.quit)
    socket.connectToServer(server_name)
    loop.exec()
    socket.abort()
    socket.deleteLater()
    return delivered[0]
