# Changelog

## 0.1.1 (2026-08-13)

Hardening release — data integrity and single-writer correctness.

- Strict BOARD save contract: a board with any structural error (malformed
  line/fragment, duplicate ID, duplicate field, missing/duplicate heading,
  checkbox contradiction) is never silently canonicalized; corrupt bytes are
  preserved to `.history/corrupt-<ts>.board.md` before validated snapshot
  recovery.
- Transactional mutations: every controller change mutates a candidate board
  and adopts it only after persistence succeeds — a refused save leaves
  memory, disk, undo stacks and LOG untouched.
- Transactional undo/redo (peek/commit, atomic rewrites, corrupt-history
  skipping); external edits block undo until the conflict is resolved.
- Trash identity is an immutable record_id; restores are peek-then-commit so
  a failed restore never loses the trash copy.
- Conflict resolution preserves BOTH sides (external and local conflict
  copies); the banner re-arms for repeated conflicts.
- Single-instance contract: mutex is authority; a second instance hands off
  with a shared nonce + ACK and exits — it can never become a second writer.
- Per-key config validation, never-throwing theme validation with emergency
  fallback, Windows/non-Windows test separation.
- Plan Review is low-noise (valid dependency chains never warn); immutable
  Unicode-safe plan ids; structured PLAN.md (unknown sections preserved);
  transactional plan creation; archive restores exact identity.
- Break Down is an atomic validated batch; checklist is in the field contract.
- Timers: atomic persistence, invalid repeat intervals rejected, truthful
  wall-clock crash recovery, stopwatch/pomodoro/countdown UI fixes.
- 238 tests, ruff clean, Windows portable Nuitka build smoke.

## 0.1.0 (2026-08-13)

Initial release of SAIPLAN, a lightweight portable Windows planner with
SAIPEN-style planning for ordinary humans.

- BOARD kanban: DOING / TODO / DONE / BLOCKED, drag/drop + keyboard, WIP badge.
- Plain Markdown authority: BOARD.md is the canonical task state.
- First-run flow: create plan → focused quick-add → ticket in TODO in 3 actions.
- Inspector: priority, due, tags, dependencies, checklist, notes, ticket timer.
- Break Down wizard (goal → constraints → definition of done → atomic tasks).
- Plan Review: vague/duplicate/cyclic/impossible-dependency warnings.
- Data safety: atomic writes, validated rotating snapshots, one-way mirror,
  persisted undo/redo, trash, external-edit detection with conflict copies.
- Timers: countdown, stopwatch, Pomodoro, ticket timers into TIMELOG.jsonl.
- Sounds: 414-event library with preview and per-event mapping.
- Themes: all 16 Wintage packs, Golden Vintage default, runtime switching.
- Portability: single exe folder, data/assets/config move together.
