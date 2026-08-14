"""Real entry-point smoke: launch the actual `python -m saiplan.main` in a
subprocess, offscreen, with an auto-quit, and verify a clean exit.

This exercises logging, portable layout, single instance, config, theme
registry, timer engine and the full window build — the true definition-of-done
path, not a mocked replica.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = [
    pytest.mark.slow,
    pytest.mark.subprocess,
    pytest.mark.integration,
    pytest.mark.qt,
]


def test_main_entrypoint_launches_and_exits(tmp_path):
    root = tmp_path / "SAIPLAN"
    env = dict(os.environ)
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["SAIPLAN_ROOT"] = str(root)
    env["SAIPLAN_AUTOQUIT_MS"] = "1200"
    source = str(Path(__file__).resolve().parents[1] / "src")
    env["PYTHONPATH"] = source + os.pathsep + env.get("PYTHONPATH", "")
    proc = subprocess.run(
        [sys.executable, "-m", "saiplan.main"],
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
        cwd=tmp_path,
        check=False,
    )
    assert proc.returncode == 0, f"stderr:\n{proc.stderr}"
    assert "SAIPLAN starting" in proc.stderr or (root / "logs").exists()
    assert (root / "data").exists()
    assert (root / "data" / "config.json").exists()


def test_main_entrypoint_readonly_data_fails_loudly(tmp_path):
    root = tmp_path / "SAIPLAN"
    root.mkdir()
    (root / "data").write_text("i am a file, not a directory", encoding="utf-8")
    env = dict(os.environ)
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["SAIPLAN_ROOT"] = str(root)
    source = str(Path(__file__).resolve().parents[1] / "src")
    env["PYTHONPATH"] = source + os.pathsep + env.get("PYTHONPATH", "")
    proc = subprocess.run(
        [sys.executable, "-m", "saiplan.main"],
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
        cwd=tmp_path,
        check=False,
    )
    assert proc.returncode == 2  # loud refusal, no silent data scatter
    assert "data" in (proc.stderr + proc.stdout).lower()
