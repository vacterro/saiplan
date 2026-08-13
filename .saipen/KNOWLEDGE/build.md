# SAIPLAN build & check commands

Canonical commands for this project (first written at SCOUT T-008).

- Unit/UI tests: `pytest -q` (root dir). 150 tests. UI smoke needs
  `QT_QPA_PLATFORM=offscreen`. Slow entry smoke: `pytest tests/test_main_entry.py`.
- Lint: `python -m ruff check src tests`
- Format: `python -m ruff format src tests`
- Portable Windows build: `powershell -File build_windows.ps1` (Nuitka + MSVC).
- Dev install: `pip install -e .[dev]`.
- Entry point: `python -m saiplan.main`; CI hook env
  `SAIPLAN_ROOT=<dir>` + `SAIPLAN_AUTOQUIT_MS=<ms>` + `QT_QPA_PLATFORM=offscreen`.
