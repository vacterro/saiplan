# SAIPLAN — Architecture

## Product essence

"Write what needs doing. SAIPLAN makes the plan explicit. Do the next thing.
Nothing gets lost."

Goal/task → decompose into clear tickets → BOARD → execute → verify → DONE.
The user must understand the application without reading documentation.

## Mode decision (spec §1): ordinary human, Mode B

SAIPLAN runs SAIPEN-**style** planning. Default projects are **ordinary SAIPLAN
projects**:

- SAIPLAN-owned plain files under `data/plans/<plan-id>/`
- readable by any text editor, no `.saipen/` directory is fabricated
- explicitly labeled "SAIPEN-style planning", NEVER "SAIPEN protocol compliant"

Mode A (native SAIPEN project, canonical `.saipen/` files, canonical SAIOPS
mutations) is a **later, separate** feature behind an explicit
"Export/Convert to SAIPEN project" action. SAIPLAN never writes an incompatible
pseudo-SAIPEN dialect. There is no `.saipen/` in SAIPLAN v1 data.

## Layout (portable folder)

```
SAIPLAN/
  SAIPLAN.exe            (built from src/, Nuitka)
  data/
    config.json          app settings (theme, scale, hotkeys, mirror dir, retention…)
    plans/
      <plan-id>/
        PLAN.md          objective, constraints, definition of done, metadata
        BOARD.md         canonical task state (THE authority)
        LOG.md           semantic plan history
        TIMELOG.jsonl    ticket timer sessions
        notes/           per-plan notes (markdown)
        attachments/
        .history/        undo log + rotating board snapshots
        .history/trash.jsonl   deleted ticket records, recoverable
  themes/                Wintage 21-token JSON packs (16 shipped)
  sounds/                full FastPrompter library as assets (414 wav)
  logs/                  app debug/crash logs (separate from semantic LOG.md)
```

Moving/copying the whole directory moves the complete installation **and its
data** (I14). If the app directory is read-only: fail loudly or offer an
explicit alternate writable data location — never silently scatter plan data
(I14 / spec §10).

`config.json` defaults live next to the exe; unknown/corrupt config falls back
to defaults, never refuses to start (SAIPENVIEW config pattern).

## One source of truth per datum (I10)

- BOARD.md = canonical task state. No SQLite mirror. No cache that is not
  rebuildable and disposable.
- config.json = app settings.
- TIMELOG.jsonl = timer sessions.
- LOG.md = semantic events (append-only).
- `themes/*.json` = the ONLY theme token source (I12). Palette values never
  copied into source files.

## Core modules

```
src/saiplan/
  core/
    model.py        Plan, Ticket, statuses, lifecycle validation
    board.py        strict BOARD.md parser/writer (line grammar, escaped pipes)
    persistence.py  atomic write (temp+flush+fsync+replace), backup/snapshots,
                    mirror, conflict detection, crash recovery (BoardStore.recover)
    history.py      persisted undo/redo command log + trash
    config.py       app config (defaults + merge, atomic write)
    plan.py         plan dir lifecycle (create/open/list, PLAN.md)
    lifecycle.py    ticket transitions + id allocation
    logbook.py      semantic LOG.md writer (event vocabulary)
    review.py       Plan Review checks (vague/dup/cycle/dangling/impossible dep…)
    search.py       debounced in-memory index over board + notes
  ui/
    controller.py   one writer per plan: board + store + undo + log + trash
    board.py        kanban columns, drag/drop, keyboard movement, WIP badge
    inspector.py    right pane (collapsible): details/checklist/deps/timer/notes
    dialogs.py      create plan, break-down wizard, settings, sound, timers,
                    trash, review, stats, conflict
    shell.py        main window, plan list, search bar, shortcuts, wiring
  extras/
    timers.py       deadline timers + stopwatch + Pomodoro + ticket timers
    sounds.py       sound registry/player/preview (assets, never logic)
    notes.py        per-plan notes + backlinks
    statistics.py   compact stats from canonical files
    archive.py      archive closed plans (move to data/archive/)
  theme/
    registry.py     load/validate themes/*.json (21 tokens), Golden Vintage default
    loader.py       QSS generation from tokens (Win95 grammar)
    validation.py   token set + hex + WCAG AA gate tests
  platform/
    single_instance.py  Windows named mutex + token IPC handoff
    hotkeys.py          RegisterHotKey (ctypes, layout-aware)
    paths.py            portable path resolution + writable probe
  applog.py         rotating crash log under logs/
  main.py           entry point: logging → layout → single instance → window
```

Dependency rule: `core` imports nothing from `extras`, `ui`, `theme`,
`platform`. `ui` depends on core only. Extras register on a bus; if an extra
fails to load it is disabled with a logged reason — BOARD still opens (I8).
BOARD stays fully usable with timers/sounds/extras disabled (I1).

## BOARD.md format

Canonical section order and headings:

```
## DOING
## TODO
## DONE
## BLOCKED
```

Ticket line (SAIPEN grammar + human fields):

```
- [ ] S-001 Buy and install new SSD | due: 2026-08-20 | priority: high
- [ ] S-002 Research SSD models | needs: S-001
- [x] S-003 Check M.2 slot | done-when: manual install guide reviewed
- [ ] S-004 Order | blocked-by: S-002
```

- Checkbox `[ ]` open (TODO/BLOCKED), `[/]` DOING, `[x]` DONE; section IS the
  status, checkbox must agree.
- Field separators ` | `; a literal `|` in any value escaped as `\|`; backslash
  escaped first (`\\`).
- Field vocabulary is closed: structural `id, title, status`; optional human
  fields `priority, due, tags, needs, estimate, done-when, blocked-by, details,
  checklist, created, updated`. An unknown but well-formed `key: value` field
  is a WARNING and its value is preserved semantically; canonical rendering may normalize layout.
- A board that parses with ANY structural error (malformed line, malformed
  field fragment, duplicate ID, duplicate single-valued field, missing/
  duplicate required heading, ticket under unknown heading, checkbox/section
  contradiction) is NOT writable: the bytes are preserved as
  `.history/corrupt-<ts>.board.md` and the validated snapshot is restored.
- Stable ID `S-###` per plan, monotonic, never reused, survives rename/drag/
  restart/sorting. Next id = max across BOARD + LOG (SAIPEN rule).
- `needs:` lists `S-###` dependencies; `blocked-by` is a free-text reason
  (present iff section == BLOCKED).
- New ticket → TODO by default (I2).

Board is the authority; LOG.md is history. Write order: BOARD atomically first
(flush+fsync+replace), then LOG append. A crash between the two leaves BOARD
ahead of LOG, which is truthfully the newer state (inverted commit-pointer
rule, safe for a file whose LOG is not authoritative).

## Persistence & data safety (spec §9)

WRITE: serialize new BOARD text → `BoardStore.save()` REFUSES any text that is
not a strictly valid, losslessly representable BOARD (empty or partial boards
are rejected BEFORE any write) → atomic write (`BOARD.md.tmp-<rand>` → flush →
fsync → `os.replace`) → update in-memory guard. Never write directly to the
target.

TRANSACTIONAL MUTATIONS: the controller never mutates the live board before
persistence succeeds. Every mutation goes through `_transaction`:
current → clone/candidate → mutate candidate → render → strict validate →
`store.save()` → record history/log → ONLY THEN adopt the candidate. A refused
save (external edit, validation error) leaves memory, disk, undo stacks and
LOG untouched.

BACKUP: `.history/` rotating snapshots — human-readable `.md` copies of
BOARD.md, rotation configurable (default keep 14), validated STRICTLY before
accept (non-empty, parses with zero structural errors). A new empty/corrupt
state NEVER overwrites a healthy backup.

MIRROR: optional one-way mirror directory (config). Write-only copy of each
save; never delete from mirror; never read mirror back into canonical state.

UNDO: `.history/undo.jsonl` append-only command log. Undo/redo are
TRANSACTIONAL (peek inspects without moving the stack; commit moves a record
only after the candidate board was persisted) and survive restart. Corrupt
JSON lines and records missing required fields are skipped, never raised;
stack rewrites are atomic. Trash: deleted tickets → `.history/trash.jsonl`
with an immutable `record_id` (identity is never a timestamp); restore is
peek → persist candidate board → mark restored (duplicate metadata is kept
over a lost ticket).

EXTERNAL EDIT: SAIPLAN loads BOARD.md, records `(sha256, mtime)` as a guard.
A bounded 2-second active-file poll compares the fingerprint — documented
trade-off for a small canonical file (the two-file watcher from the original
audit sketch was simplified; the causal model is unchanged). On mismatch the
UI shows a conflict banner. Resolution preserves BOTH sides explicitly:
"keep mine" writes the EXTERNAL bytes to `BOARD.conflict-external-<ts>.md`
before the local version takes the canonical file; "reload external" writes
the LOCAL bytes to `BOARD.conflict-local-<ts>.md` before adopting the external
version. Neither side is ever destroyed.

RECOVERY on startup: read BOARD.md; if missing/corrupt → preserve the corrupt
bytes to `.history/corrupt-<ts>.board.md`, restore the newest validated
snapshot atomically (`recover_and_adopt`), adopt it as the loaded state
(disk/loaded_text/guard agree), LOG `RECOVERY_USED`. No valid snapshot → the
plan becomes READ-ONLY: mutations, undo and redo are refused loudly, never a
silent empty reset.

## Undo semantics

- Every mutating op (create/edit/move/status/delete) appends to undo.jsonl and
  truncates redo.
- Undo restores prior BOARD bytes for that op (or prior field value), redo
  re-applies. Ops persist across restart.
- Delete → appends ticket record to `.history/trash.jsonl` + a `DELETED` marker in
  BOARD? No — delete = remove line + trash record; restore re-inserts.

## Timers (extras, spec §11)

Two engines (FastPrompter split):
- **Deadline timer**: absolute wall-clock target (ISO UTC persisted, saved
  atomically), repeat advance() into future, snooze always later, corrupt
  entries and invalid repeat intervals (≤0 / NaN / inf) skipped safely.
- **Stopwatch/Pomodoro**: elapsed-time driven, pause/resume/skip. Run state
  does NOT survive restart, and the stopwatch's accumulated elapsed is
  in-memory only — after a restart it comes back idle at 0 (documented truth,
  matching the implementation; the doc no longer claims otherwise).
- **Ticket timer**: start on selected ticket; records
  `{ticket_id, started_at, ended_at, duration_s, kind}` into TIMELOG.jsonl.
  Monotonic clock during process lifetime; persisted wall-clock UTC for
  restart recovery. A session left open by a crash is closed at next load
  with a TRUTHFUL wall-clock duration estimate
  (`duration_source: wall_clock_estimate`) — never silently zeroed. Timer
  engine runs without the timers tab visible.

## Sounds (extras, spec §12)

- 414 wav files shipped as assets under `sounds/`, enumerated dynamically
  (recursive, forward-slash relative names).
- Nested paths resolve via pathlib parts (platform-neutral); `..` escapes are
  rejected.
- Events: timer_finished, pomodoro_work_done, break_finished, due_reminder,
  ticket_done, blocked_warning, plan_completed (+ UI niceties: click, undo…).
- Per-event `{file, enabled, volume}`; stale-name heal on load; preview
  bypasses toggles; missing/corrupt file → silent skip, never crash;
  `winsound` fallback with sample rescaling for volume (QtMultimedia optional).
- Semantic wiring is a UI adapter: the controller exposes `last_event` after
  a committed mutation; the shell maps TICKET_DONE → ticket_done,
  TICKET_BLOCKED → blocked_warning, plan-fully-completed → plan_completed.
  Core never depends on sound.

## Themes (spec §13)

- Ship all 16 Wintage `themes/*.json` verbatim into `themes/`.
- One registry, one 21-token schema. `validate_theme(any JSON) -> list[str]`
  NEVER raises (a token that is an int, a list, null, or broken hex cannot
  crash validation); unknown/corrupt theme → Golden Vintage fallback, and if
  even that is missing → an emergency palette keeps the app running (I8 is
  executable, not aspirational). Runtime switching, no restart.
- QSS generator emits Win95 grammar: square corners, 2px bevel
  (light top-left / dark bottom-right), raised buttons, sunken editors,
  inverted bevel when pressed, zero radius, no decorative animation.
- Test: every shipped theme parses, carries all 21 tokens, passes WCAG AA on
  the 3 text roles vs backgroundSoft.

## Single instance (spec §8/§17) — mutex is AUTHORITY

- Windows named mutex (`Local\Saiplan`) held for the process lifetime. The
  mutex alone decides who may WRITE: first → writer; not first → never a
  writer, ever.
- A second instance reads a SHARED nonce (rendezvous file `data/.instance-nonce`,
  written by the first instance) and sends it over QLocalServer; the first
  replies with an explicit ACK. Delivery is reported only when the ACK arrives.
- On ACK → second activates and exits 0. No ACK within the bounded startup
  grace → second exits 1 with a clear message. It NEVER falls through to
  becoming a second writer because IPC failed.
- A hard-killed first releases the kernel mutex; the next process legitimately
  becomes first.

## Logging (spec §18)

- `LOG.md`: semantic events only:
  PLAN_CREATED, TICKET_CREATED, TICKET_STARTED, TICKET_BLOCKED,
  TICKET_UNBLOCKED, TICKET_DONE, TICKET_REOPENED, TICKET_EDITED,
  TICKET_DELETED, TICKET_RESTORED, BATCH_CREATED, PLAN_REVIEWED,
  RECOVERY_USED, CONFLICT_DETECTED. Chronological, concise.
- `logs/saiplan.log`: rotating debug/crash log (1 MB × 2). Separate from
  semantic LOG.md.

## Plan Review (spec §5) — low-noise

WARN (actionable/contradictory): empty plan, duplicate title, dangling
`needs:` (references a ticket that is not on the board), dependency cycle,
DOING ticket whose prerequisites are not DONE, DONE ticket whose own
prerequisites are not DONE, BLOCKED without a blocked-by reason, multiple
DOING under single-focus mode.
INFO (optional only): no completion criterion set, short title.
Waiting on a legitimate open prerequisite is NORMAL and never warned; the old
"DONE but still needed by" check was removed as noise.
Warnings advise; only structurally corrupt state blocks.

## Plan identity + PLAN.md (spec §16/17)

- `plan_id` is immutable: `<slug>-<short-id>` (uuid suffix). Human names stay
  Unicode in PLAN.md; multilingual names never collapse onto one id; rename
  never changes identity.
- PLAN.md is a small structured document: known sections (Objective,
  Constraints, Definition of Done) plus title/created are editable; ANY other
  section a human wrote is preserved verbatim.
- Plan creation is transactional: staged under `plans/.creating-<uuid>/`,
  validated, then atomically renamed into place; a crash leaves no partial
  plan. `PLAN_CREATED` is appended to the plan LOG.
- Archive writes `archive.json` (original_plan_id + archived_at); restore
  returns the plan to EXACTLY that id (identity is never reconstructed from a
  filename). Archiving the active plan detaches its controller and stops its
  ticket timers first.
- Break Down is an atomic batch: the whole PlanProposal is validated first,
  previewed, then committed in one transaction; invalid batches create
  nothing.

## Product invariants (pinned here AND as tests)

- I1 BOARD useful without any extra module.
- I2 New tickets enter TODO by default.
- I3 Plain files readable without SAIPLAN.
- I4 No accepted save silently discarded.
- I5 External edits never silently overwritten.
- I6 Deleted information recoverable by default.
- I7 Core has no cloud/provider dependency.
- I8 Extras cannot block Core startup.
- I9 SAIPLAN never claims canonical SAIPEN compatibility unless canonical
  invariants hold.
- I10 One source of truth per datum.
- I11 Golden Vintage is default.
- I12 Every shipped theme comes from the shared registry.
- I13 Timers survive UI recreation/restart correctly.
- I14 Portable means data/assets/config move together.
- I15 UI never requires documentation for basic TODO → DOING → DONE.

## AI boundary (spec §16, prepared, not built)

Core accepts a structured `PlanProposal` (goal → constraints → DoD → tasks →
deps). Provider adapters produce `PlanProposal`; SAIPLAN validates structure;
human accepts; tickets enter TODO. AI never owns persistence. No provider
assumptions in Core.

## Anti-bloat gate (spec §23)

Before any feature: does it make planning clearer? Make execution
safer/faster? Protect user data? Genuinely useful optional extra? If all NO —
not implemented.

## Build & release (Windows portable)

Portable folder = source layout already: `SAIPLAN.exe` next to `data/`,
`themes/`, `sounds/`, `logs/`. Canonical pipeline (pinned deps, identity
gate, manifest, smoke):

```powershell
powershell -File bootstrap-build-env.ps1       # pinned venv, once
powershell -File build_windows.ps1             # Nuitka + identity + smoke
powershell -File scripts/package_source.ps1    # clean source zip
powershell -File scripts/package_portable.ps1  # portable zip + manifest
```

Underneath, Nuitka (auto-provisions MinGW64 via
`--assume-yes-for-downloads`) compiles the root `main.py` shim
(`from saiplan.main import main`) into a standalone folder; package-relative
imports would break under a top-level `__main__` without the shim.
`build_windows.ps1` refuses a dirty tracked worktree, pins Nuitka 4.1.3,
hashes the source before/after the compile (artifact rejected if it changed),
writes `BUILD-SOURCE.sha256` + `MANIFEST.sha256` and runs an offscreen smoke
with the frozen exe.

Sound assets stay OUTSIDE the executable on purpose (spec §10): the dist
already carries `sounds/` beside the exe, and `data/` moves with the folder
(I14). Do not bundle 400 wav files into the binary.

Pre-release gate: `pytest -q` green (including explicit Qt/subprocess lanes),
`ruff check src tests` clean, and the §24 definition-of-done checklist in
`docs/RELEASE_CHECKLIST.md` manually exercised on a copy of the portable
folder (machine lanes are `[auto]` and scripted; the human walk is `[manual]`).
