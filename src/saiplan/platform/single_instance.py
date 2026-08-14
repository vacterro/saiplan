"""Single instance: Windows named mutex (AUTHORITY) + nonce/ACK IPC handoff.

The mutex is the only source of truth on "someone is running" (kernel-owned,
auto-released on hard kill). A process that does NOT own the mutex MUST NOT
become a writer to the shared BOARD — it attempts a handoff to the running
instance and then exits either way. Handoff is convenience only, never
authorization to run.

The handoff uses a SHARED nonce rendezvous file (per app data dir, written
by the first instance): the second instance reads the nonce, sends it over
QLocalServer, and the first replies with an explicit ACK. Delivery is only
reported when the ACK arrives — merely writing bytes is not success.
"""

from __future__ import annotations

import ctypes
import secrets
import sys
from pathlib import Path

ERROR_ALREADY_EXISTS = 183
kernel32 = None

if sys.platform == "win32":
    kernel32 = ctypes.windll.kernel32

NONCE_FILE = ".instance-nonce"
_ACK = b"ACK\n"


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
    """Random token authenticating a handoff (never guessable)."""
    return secrets.token_urlsafe(24)


def write_nonce(layout: dict, nonce: str) -> None:
    """Persist the first instance's handoff nonce into the shared app data
    dir so a second instance can authenticate itself."""
    from .paths import resolve_layout  # noqa: F401  (kept lazy, no cycles)

    path = Path(layout["data"]) / NONCE_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    # atomic: a torn nonce must never be readable as a valid one
    tmp = path.with_suffix(".tmp")
    tmp.write_text(nonce, encoding="utf-8")
    tmp.replace(path)


def read_nonce(layout: dict) -> str | None:
    try:
        value = (Path(layout["data"]) / NONCE_FILE).read_text(encoding="utf-8").strip()
        return value or None
    except OSError:
        return None


def handoff_available() -> bool:
    """Qt is required for QLocalServer/QLocalSocket handoff."""
    try:
        from PyQt6.QtNetwork import QLocalServer, QLocalSocket  # noqa: F401

        return True
    except Exception:  # noqa: BLE001
        return False


def notify_existing_instance(server_name: str, layout: dict, timeout_ms: int = 600) -> bool:
    """Send the shared nonce to the running instance and wait for its ACK.

    Returns True ONLY when the ACK was received. Bounded by a timer so a dead
    or rejecting server never hangs the second instance.
    """
    from PyQt6.QtCore import QEventLoop, QTimer
    from PyQt6.QtNetwork import QLocalSocket

    nonce = read_nonce(layout)
    if nonce is None:
        return False  # first instance has not published its nonce yet
    socket = QLocalSocket()
    loop = QEventLoop()
    acked = [False]
    response = bytearray()

    def _connected():
        socket.write(nonce.encode("utf-8"))
        socket.flush()

    def _ready_read():
        response.extend(bytes(socket.readAll()))
        if _ACK in response:
            acked[0] = True
            loop.quit()

    socket.connected.connect(_connected)
    socket.readyRead.connect(_ready_read)
    socket.errorOccurred.connect(lambda _e: loop.quit())
    QTimer.singleShot(timeout_ms, loop.quit)
    socket.connectToServer(server_name)
    loop.exec()
    socket.abort()
    socket.deleteLater()
    return acked[0]
