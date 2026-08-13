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
        .trash/          deleted tickets/attachments, recoverable
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
  logging.py        rotating crash log under logs/
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
- Field vocabulary is closed: `id, title, status` are structural; optional
  human fields `priority, due, tags, needs, estimate, done-when, blocked-by,
  notes-ref, created, updated`. Unknown field → surfaced as warning, never
  silently dropped, never last-write-wins.
- Stable ID `S-###` per plan, monotonic, never reused, survives rename/drag/
  restart/sorting. Next id = max across BOARD + LOG (SAIPEN rule).
- `needs:` lists `S-###` dependencies; blocked-by is a free-text reason
  (present iff section == BLOCKED).
- New ticket → TODO by default (I2).
- BOARD soft cap ~32 KB → collapsible DONE + archive keeps startup fast
  (spec §20).

Board is the authority; LOG.md is history. Write order: BOARD atomically first
(flush+fsync+replace), then LOG append. A crash between the two leaves BOARD
ahead of LOG, which is truthfully the newer state (inverted commit-pointer
rule, safe for a file whose LOG is not authoritative).

## Persistence & data safety (spec §9)

WRITE: serialize new BOARD text → write `BOARD.md.tmp-<rand>` in same dir →
flush → fsync → `os.replace` → update in-memory saved hash. Never write
directly to the target.

BACKUP: `.history/` rotating snapshots — human-readable `.md` copies of
BOARD.md (and LOG tail), rotation configurable (default keep 14), validated
before accept (non-empty, parses, hash matches). A new empty/corrupt state
NEVER overwrites a healthy backup.

MIRROR: optional one-way mirror directory (config). Write-only copy of each
save; never delete from mirror; never read mirror back into canonical state.

UNDO: `.history/undo.jsonl` append-only command log (op, ticket, old/new
field bytes, timestamp). Undo/redo replay across restart. Trash: deleted
ticket/plan/attachment → `.trash/` (JSONL + file moves), restore works after
restart.

EXTERNAL EDIT: SAIPLAN loads BOARD.md, records `(sha256, mtime)`.
On refresh/check: if bytes changed and not self-written → mark external.
Never silently overwrite: reload, merge safely (self-change wins only on
explicit user choice), or write `BOARD.conflict-<ts>.md` and keep both.
SelfWriteRegistry pattern (SAIPENVIEW) attributes our own writes so the
watcher does not flag them.

RECOVERY on startup: read BOARD.md; if missing/corrupt → try latest validated
`.history` snapshot; if none → loud refusal with crash log, never a silent
empty reset. LOG `RECOVERY_USED`.

## Undo semantics

- Every mutating op (create/edit/move/status/delete) appends to undo.jsonl and
  truncates redo.
- Undo restores prior BOARD bytes for that op (or prior field value), redo
  re-applies. Ops persist across restart.
- Delete → moves ticket line to `.trash/tickets.jsonl` + a `DELETED` marker in
  BOARD? No — delete = remove line + trash record; restore re-inserts.

## Timers (extras, spec §11)

Two engines (FastPrompter split):
- **Deadline timer**: absolute wall-clock target (ISO UTC persisted), repeat
  advance() into future, snooze always later, corrupt entries skipped.
- **Stopwatch/Pomodoro**: elapsed-time driven, pause/resume/skip, run state does
  NOT survive restart (would be a lie).
- **Ticket timer**: start on selected ticket; records
  `{ticket_id, started_at, ended_at, duration_s, kind}` into TIMELOG.jsonl.
  Monotonic clock during process lifetime; persisted wall-clock UTC for
  restart recovery; survives sleep/wake; completion event fires once
  (idempotent). Timer engine runs without the timers tab visible.

## Sounds (extras, spec §12)

- 414 wav files shipped as assets under `sounds/`, enumerated dynamically
  (recursive, forward-slash relative names).
- Events: timer_finished, pomodoro_work_done, break_finished, due_reminder,
  ticket_done, blocked_warning, plan_completed (+ UI niceties: click, undo…).
- Per-event `{file, enabled, volume}`; stale-name heal on load; preview
  bypasses toggles; missing/corrupt file → silent skip, never crash;
  `winsound` fallback with sample rescaling for volume (QtMultimedia optional).

## Themes (spec §13)

- Ship all 16 Wintage `themes/*.json` verbatim into `themes/`.
- One registry, one 21-token schema. Unknown/corrupt theme → Golden Vintage
  fallback. Runtime switching, no restart.
- QSS generator emits Win95 grammar: square corners, 2px bevel
  (light top-left / dark bottom-right), raised buttons, sunken editors,
  inverted bevel when pressed, zero radius, no decorative animation.
- Test: every shipped theme parses, carries all 21 tokens, passes WCAG AA on
  the 3 text roles vs backgroundSoft.

## Single instance (spec §8/§17)

- Windows named mutex (`Local\Saiplan_Write`) acquired for process lifetime.
  Mutex = authority on "someone is running".
- Second instance: token-authenticated QLocalServer handoff → first instance
  shows its window, second exits. No ACK within grace → exit unresponsive,
  never become a second writer.

## Logging (spec §18)

- `LOG.md`: semantic events only:
  PLAN_CREATED, TICKET_CREATED, TICKET_STARTED, TICKET_BLOCKED,
  TICKET_UNBLOCKED, TICKET_DONE, TICKET_REOPENED, TICKET_EDITED,
  TICKET_DELETED, PLAN_REVIEWED, RECOVERY_USED, CONFLICT_DETECTED.
  Chronological, concise.
- `logs/saiplan.log`: rotating debug/crash log (1 MB × 2). Separate from
  semantic LOG.md.

## Plan Review (spec §5)

Checks: vague ticket (no verb / < 4 words heuristic), duplicate title, circular
`needs:`, `needs:` missing ticket, DONE ticket with unresolved dependents
contradiction, TODO with impossible dependency, empty plan, multiple DOING when
single-focus configured, ticket without `done-when` where applicable.
Warnings advise; only structurally corrupt state blocks.

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
`themes/`, `sounds/`, `logs/`. Build with Nuitka (MSVC required):

```powershell
# from repo root, in a venv with `pip install -e .[build,dev]`
python -m nuitka --standalone --windows-console-mode=disable `
  --enable-plugin=pyqt6 --assume-yes-for-downloads `
  --include-package=saiplan --output-dir=build src\saiplan\main.py
# copy to a portable folder next to the assets
New-Item -ItemType Directory -Force dist\SAIPLAN\data\plans
Copy-Item build\main.dist\* dist\SAIPLAN\ -Recurse
Copy-Item themes sounds dist\SAIPLAN\ -Recurse
```

Sound assets stay OUTSIDE the executable on purpose (spec §10): the dist
already carries `sounds/` beside the exe, and `data/` moves with the folder
(I14). Do not bundle 400 wav files into the binary.

Pre-release gate: `pytest -q` green (150+ tests incl. subprocess entry smoke),
`ruff check src tests` clean, and the §24 checklist manually exercised on a
copy of the portable folder.
