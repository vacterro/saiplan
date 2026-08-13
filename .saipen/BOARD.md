# Board

## DOING

## TODO

## DONE
- [x] T-013 WAVE A data integrity: strict BOARD load/save contract (partial boards never saved; corrupt primary preserved before recovery), transactional controller (_transaction candidate board), transactional undo/redo (peek/commit), unique record_id trash with peek-then-commit restore, both-sides conflict preservation, recover_and_adopt | verify: pytest -q -> 238 passed; tests/test_persistence.py + test_history.py + test_controller.py
- [x] T-014 WAVE B single writer/startup: mutex-authority single instance with nonce+ACK handoff (second never becomes writer), startup grace, per-key config validation, never-throwing theme validation with emergency fallback, Windows/non-Windows test separation | verify: tests/test_single_instance.py -> 4 passed (real subprocess handoff/refusal/kill-recovery)
- [x] T-015 WAVE C primary UX: QuickAdd refresh + failure text retention, inspector refresh after transitions/delete, single priority control, checklist in field contract, structured PLAN.md (unknown sections preserved), atomic Break Down batch, low-noise Plan Review, immutable unicode plan ids, transactional plan create, archive exact-identity restore | verify: pytest -q -> 238 passed; tests/test_ui_smoke.py + test_plan_hardening.py + test_review.py
- [x] T-016 WAVE D extras: timer atomic persistence + invalid repeat rejection + truthful wall-clock crash recovery + stopwatch/pomodoro/countdown fixes; sound nested path platform-neutral + traversal rejected; notes atomic/unicode; search/docs truth pass | verify: tests/test_timers.py + test_sounds.py + test_extras.py
- [x] T-017 WAVE E release: caches cleaned, ruff clean, 238 pytest green, Nuitka rebuild + dist launch/copy-folder/kill-restart/second-instance smoke all exit 0 | verify: dist/SAIPLAN/SAIPLAN.exe launches (log: start + rc 0); copied folder launch exit 0; second instance handoff exit 0 in 1s while first alive; killed first -> next becomes first; committed 5b9252b
- [x] T-010 Nuitka portable build via build_windows.ps1 | verify: dist/SAIPLAN/SAIPLAN.exe exists and launches with SAIPLAN_AUTOQUIT_MS -> exit 0 (Nuitka self-provisioned MinGW; committed dbc8230)
- [x] T-009 AI boundary interface: PlanProposal dataclass + structural validator in core (spec §16 "prepare interfaces, no provider soup"); provider adapters produce it, human accepts, tickets enter TODO | verify: tests/test_ai_boundary.py -> 9 passed; full suite 159 passed; committed 69c9ebb
- [x] T-008 Version-control the project: git init, .gitignore sweep, first commit of the whole SAIPLAN tree | verify: git log -1 -> e92bb9a initial commit covering src/tests/docs/themes/sounds/.saipen; git status --porcelain clean
- [x] T-012 Hotkey resolution defect: Latin letters must map to fixed virtual keys (VkKeyScanW returns -1 for a/k/K on non-Latin layouts, e.g. RU 0x0419); symbols stay layout-aware | verify: tests/test_platform.py asserts fixed VK for Ctrl+K / Ctrl+Shift+K and only the contract for symbols; full suite pytest -q -> 150 passed
- [x] T-001 Audit four repos (FastPrompter/SAIPENVIEW/SAIPEN/Wintage) against HEAD, write docs/REFERENCE_AUDIT.md compact matrix | verify: matrix row per mechanism; 414 wav + 16 theme JSONs byte-identical to sources (verified by hash diff)
- [x] T-002 Core data layer: model, strict BOARD parser/writer, atomic persistence (temp+fsync+replace), validated snapshots, mirror, recovery, persisted undo/redo, trash, lifecycle transitions, semantic LOG, Plan Review, search | verify: pytest -q -> 150 passed
- [x] T-003 Themes: one registry + 21-token validation + WCAG AA gate + Win95 QSS loader; all 16 Wintage packs shipped, Golden Vintage default + emergency fallback | verify: pytest tests/test_themes.py -> 13 passed; every shipped theme loads and passes WCAG AA
- [x] T-004 Platform: portable path resolution, writable probe, named-mutex single instance + token handoff, layout-aware hotkeys, rotating crash log | verify: pytest tests/test_platform.py -> 11 passed
- [x] T-005 Extras: Qt-free timer engine (deadline/stopwatch/pomodoro/ticket timers, restart+crasher recovery, idempotent fire) + sound library (414 wav, dynamic enumerate, per-event map, missing-file safety) | verify: pytest tests/test_timers.py tests/test_sounds.py -> green
- [x] T-006 UI: kanban board (drag/drop + keyboard + WIP), collapsible inspector, dialogs (plan/breakdown/settings/sounds/timers/trash/review/conflict), main window, first-run quick-add | verify: pytest tests/test_ui_smoke.py (offscreen) -> 8 passed
- [x] T-007 Entry point + release tooling: main.py (logging->layout->single-instance->window, autoquit CI hook), build_windows.ps1, offscreen subprocess smoke | verify: pytest tests/test_main_entry.py -> 2 passed; ruff check src tests clean

## BLOCKED
- [ ] T-011 Real on-screen launch + manual polish pass of the §24 definition-of-done checklist | blocker: manual on-screen human pass required -- agent verified offscreen launch (exit 0) + copied-folder portability, but the real GUI walk and all-16-themes switch need a human at the machine | verify: MANUAL -- human launches SAIPLAN.exe, walks TODO->DOING->DONE, switches all 16 themes
