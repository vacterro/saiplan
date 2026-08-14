# SAIPLAN build & check commands

Canonical commands for this project (first written at SCOUT T-008).

- Full gate: `python -m pytest -q`. Platform-neutral lane:
  `python -m pytest -q -m "not subprocess"`. Process lane:
  `python -m pytest -q -m subprocess`. Qt smoke uses offscreen automatically.
- Lint: `python -m ruff check src tests`
- Format gate: `python -m ruff format --check src tests`
- Build bootstrap: `powershell -File bootstrap-build-env.ps1`; portable build:
  `powershell -File build_windows.ps1`. Compiles root
  `main.py` (thin shim) so the package keeps relative imports; output exe is
  renamed SAIPLAN.exe. ccache makes rebuilds fast. `build_windows.ps1` gates on
  clean tracked worktree, pinned Nuitka 4.1.3, pre/post source identity, and
  writes BUILD-SOURCE.sha256 + MANIFEST.sha256 + offscreen exe smoke.
- Release packages: `powershell -File scripts/package_source.ps1` (clean
  source zip, junk gate) and `powershell -File scripts/package_portable.ps1`
  (build + portable verify + zip). Verification core:
  `python scripts/verify_release.py <source|portable|identity> --root <dir>`.
- Dev install: `pip install -e .[dev]`.
- Entry point: `python -m saiplan.main`; CI hook env
  `SAIPLAN_ROOT=<dir>` + `SAIPLAN_AUTOQUIT_MS=<ms>` + `QT_QPA_PLATFORM=offscreen`.
