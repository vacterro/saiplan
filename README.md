# SAIPLAN

Write what needs doing. SAIPLAN makes the plan explicit. Do the next thing.
Nothing gets lost.

SAIPLAN is a lightweight portable Windows planner that exposes SAIPEN-style
planning to an ordinary human: goal → decompose into clear tickets → BOARD →
execute → verify → DONE.

Version 0.1.1. See [CHANGELOG.md](CHANGELOG.md).

## What it is

- A kanban **BOARD** with four columns: DOING, TODO, DONE, BLOCKED.
- Plain Markdown files as the source of truth — read them in any editor,
  no database, no cloud, no account, no telemetry.
- New tickets land in TODO. Start → Done → Block → Reopen are one click or
  one keyboard shortcut.
- A right-hand **inspector** for priority, due date, tags, dependencies,
  a checklist, notes, and a per-ticket timer.
- **Break down** turns one big goal into atomic tickets with dependencies.
- **Plan Review** warns about vague tickets, duplicates, dependency cycles
  and missing completion criteria — it advises, it never blocks.
- Persisted **undo**, **trash** (nothing is ever permanently deleted), and
  rotating snapshots so a crashed machine loses nothing.
- External edits to a board are detected, never silently overwritten.

## Install

No installer. Download or copy the portable folder anywhere writable
(e.g. `C:\SAIPLAN\` or a USB stick):

```
SAIPLAN/
  SAIPLAN.exe
  data/          your plans live here
  themes/        16 Win95-style themes (Golden Vintage is default)
  sounds/        the sound library
  logs/          debug/crash logs
```

Launch `SAIPLAN.exe`. Copy the whole folder to move the complete
installation and its data together.

If the folder is read-only, SAIPLAN refuses to start instead of scattering
plan data elsewhere.

## Usage

1. **Create Plan** → name it, say what you want to accomplish.
2. Type a task into the focused quick-add box and press Enter — it appears
   in TODO.
3. **Start** a ticket (drag it to DOING, or press Ctrl+Enter).
4. **Done** when it is finished (Ctrl+D).
5. Blocked? **Block** and say why (Ctrl+B). Reopen when it clears
   (Ctrl+Shift+R).

Keyboard: `Ctrl+N` new ticket · `Ctrl+Shift+N` new plan · `Ctrl+F` search ·
`Ctrl+Z` undo · `Ctrl+Shift+Z` redo · `Ctrl+1..4` jump to a column ·
`Delete` move to Trash · `Space` start/pause the ticket timer.

## Data

Every plan is a folder under `data/plans/<plan-id>/`:

```
PLAN.md     the objective
BOARD.md    the canonical ticket state
LOG.md      semantic history
TIMELOG.jsonl   tracked work sessions
notes/      per-ticket markdown notes
.history/   undo log + rotating board snapshots
```

Board lines look like:

```
## TODO
- [ ] S-001 Buy and install new SSD | due: 2026-08-20 | priority: high
```

## Build from source

Requires Python 3.11+, `pip install -e .[dev]`.

```
pytest -q                       # 150 tests
python -m ruff check src tests
python -m ruff format src tests
powershell -File build_windows.ps1   # Nuitka portable build
```

## Extras are optional

Timers, sounds, notes, statistics and archive are optional extras. A broken
sound file, a missing theme or a failed timer never stops the BOARD from
opening — the core stays small and brutal.
