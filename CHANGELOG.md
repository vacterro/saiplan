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
- Recovery dialog: browse rotating snapshots and forensic corrupt/
  pre-restore copies, preview, and restore any validated snapshot — the
  current board is backed up byte-exact first, undo and a `SNAPSHOT_RESTORED`
  LOG event are kept, and refusals (external edit, read-only, invalid
  snapshot) leave no trace.
- Plan export/import: any plan is one portable `.saiplan` bundle (PLAN.md,
  BOARD.md, LOG.md, timelog, notes, `.history` incl. id-sequence watermark).
  Import restores EXACT identity, never clobbers an existing plan, rejects
  corrupt boards and zip-slip members, and is transactional (staged then
  atomically renamed).
- Ticket attachments: copy files into `attachments/<ticket_id>/` with
  Unicode-safe names (never overwritten, traversal impossible); removal
  moves the file byte-exact to the plan's attachments trash; ticket
  delete/undo/restore never loses them; `.saiplan` bundles carry them.
- Optional per-column WIP limits (Settings): the column badge shows
  `count/limit` and a `!` when over the cap. Advisory only — single-focus
  stays the one hard rule; caps survive restart.
- Keyboard-shortcuts cheatsheet (`Ctrl+Shift+/`): one source of truth
  (`shell.SHORTCUTS`) drives both the bindings and the reference dialog, so
  the cheatsheet can never drift from the real shortcuts.
- 327 tests (platform-neutral 321 + subprocess lane 6), ruff clean, Windows
  portable Nuitka build smoke, source/portable manifests verified.

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
- Sounds: 414-file asset library with preview and per-event mapping.
- Themes: all 16 Wintage packs, Golden Vintage default, runtime switching.
- Portability: single exe folder, data/assets/config move together.
