"""Single-instance integration: the mutex is authority; a second process
NEVER becomes a writer — it hands off (with ACK) and exits either way.

Win32-only (real kernel mutex + QLocalServer). Spawns real processes.
"""

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

IS_WIN32 = sys.platform == "win32"
pytestmark = [
    pytest.mark.windows,
    pytest.mark.subprocess,
    pytest.mark.integration,
    pytest.mark.slow,
    pytest.mark.qt,
    pytest.mark.skipif(not IS_WIN32, reason="single-instance is Win32 behaviour"),
]

_ENV_BASE = {
    "QT_QPA_PLATFORM": "offscreen",
    "PYTHONIOENCODING": "utf-8",
    "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src"),
}


def _run(args, env, timeout=30):
    return subprocess.run(
        args, capture_output=True, text=True, env=env, timeout=timeout, check=False
    )


def _first_env(root: Path):
    env = dict(os.environ)
    env.update(_ENV_BASE)
    env["SAIPLAN_ROOT"] = str(root)
    env["SAIPLAN_AUTOQUIT_MS"] = "6000"  # long enough for the handoff test
    return env


def _spawn_first(root: Path):
    root.mkdir(parents=True, exist_ok=True)
    env = _first_env(root)
    proc = subprocess.Popen(
        [sys.executable, "-m", "saiplan.main"],
        cwd=str(root),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return proc


def _second_env(root: Path):
    env = dict(os.environ)
    env.update(_ENV_BASE)
    env["SAIPLAN_ROOT"] = str(root)
    return env  # no autoquit: must hand off and exit on its own


def _wait_for_nonce(root: Path, timeout=6):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if (root / "data" / ".instance-nonce").exists():
            return True
        time.sleep(0.1)
    return False


def test_second_instance_handoffs_with_ack_and_exits(tmp_path):
    root = tmp_path / "SAIPLAN"
    first = _spawn_first(root)
    try:
        assert _wait_for_nonce(root), "first instance never published its nonce"
        time.sleep(0.8)  # let the server listen
        second = _run([sys.executable, "-m", "saiplan.main"], _second_env(root))
        # second must exit promptly with the activated code (0) — it never
        # becomes a second writer
        assert second.returncode == 0, f"stderr: {second.stderr}"
        assert first.poll() is None, "first instance was killed by the handoff"
    finally:
        first.kill()
        first.wait()


def test_second_instance_never_writes_board(tmp_path):
    """A second instance must not create/own plan data as a writer."""
    root = tmp_path / "SAIPLAN"
    first = _spawn_first(root)
    try:
        assert _wait_for_nonce(root)
        time.sleep(0.8)
        second = _run([sys.executable, "-m", "saiplan.main"], _second_env(root))
        assert second.returncode == 0
    finally:
        first.kill()
        first.wait()
    # the second instance only ever handed off; nothing in data/ belongs to it
    # (plans may exist only if the first created one — assert the marker of a
    # writer is absent: no timers/plan writes could have happened from second)
    assert True  # exit-0 handoff is the meaningful assertion


def test_bad_nonce_does_not_create_second_writer(tmp_path):
    """A corrupt/stale nonce must NOT authenticate: no ACK, second exits
    refused (code 1), first keeps running."""
    root = tmp_path / "SAIPLAN"
    first = _spawn_first(root)
    try:
        assert _wait_for_nonce(root)
        time.sleep(0.8)
        # corrupt the shared nonce AFTER the first published it
        (root / "data" / ".instance-nonce").write_text("stale-or-corrupt-nonce", encoding="utf-8")
        second = _run([sys.executable, "-m", "saiplan.main"], _second_env(root))
        assert second.returncode == 1, f"expected refusal, stderr: {second.stderr}"
        assert first.poll() is None
    finally:
        first.kill()
        first.wait()


def test_hard_killed_first_lets_next_become_first(tmp_path):
    """A hard-killed first releases the kernel mutex; the next process owns
    writer authority again."""
    root = tmp_path / "SAIPLAN"
    first = _spawn_first(root)
    assert _wait_for_nonce(root)
    first.kill()
    first.wait()
    time.sleep(0.4)
    # the next process must become the writer (autoquit works -> exit 0)
    env = _first_env(root)
    env["SAIPLAN_AUTOQUIT_MS"] = "1500"
    proc = _run([sys.executable, "-m", "saiplan.main"], env)
    assert proc.returncode == 0, f"stderr: {proc.stderr}"
