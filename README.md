# SAIPLAN

Write what needs doing. SAIPLAN makes the plan explicit. Do the next thing.
Nothing gets lost.

SAIPLAN is a lightweight portable Windows planner that exposes SAIPEN-style
planning to an ordinary human: goal → decompose into clear tickets → BOARD →
execute → verify → DONE.

Version 0.0.1. See [CHANGELOG.md](CHANGELOG.md).

## What it is

- A kanban **BOARD** with four columns: DOING, TODO, DONE, BLOCKED, and
  optional per-column **WIP limits** (Settings) — the badge shows `count/limit`
  and a `!` warns when a column is over its cap. Advisory only: single-focus
  is the one hard rule.
- Plain Markdown files as the source of truth — read them in any editor,
  no database, no cloud, no account, no telemetry.
- New tickets land in TODO. Start → Done → Block → Reopen are one click or
  one keyboard shortcut.
- A right-hand **inspector** for priority, due date, tags, dependencies,
  a checklist, notes, a per-ticket timer, and file **attachments** (copied
  into the plan folder with safe names; deleting a ticket never loses them).
- **Break down** turns one big goal into atomic tickets with dependencies.
- **Plan Review** warns about vague tickets, duplicates, dependency cycles
  and missing completion criteria — it advises, it never blocks.
- Persisted **undo**, **trash** (nothing is ever permanently deleted), and
  rotating snapshots so a crashed machine loses nothing. A **Recovery**
  dialog browses snapshots and forensic copies and restores any validated
  one — the current board is backed up byte-exact first.
- **Export / Import**: any plan is one portable `.saiplan` file (board, notes,
  history and identity travel together). Import restores the exact same plan
  and never overwrites an existing one.
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
`Delete` move to Trash · `Space` start/pause the ticket timer ·
`Ctrl+Shift+/` shows the full cheatsheet.

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

Requires Python 3.11+. Build dependencies are pinned; bootstrap once, then
build without package upgrades.

```
python -m pip install -e .[dev]
pytest -q
pytest -q -m "not subprocess"  # platform-neutral lane
pytest -q -m subprocess        # process/Windows integration lane
python -m ruff check src tests
python -m ruff format --check src tests
powershell -File bootstrap-build-env.ps1
powershell -File build_windows.ps1
powershell -File scripts/package_source.ps1
powershell -File scripts/package_portable.ps1
```

Release checklist (spec §24 definition of done, machine + human lanes):
[RELEASE_CHECKLIST.md](docs/RELEASE_CHECKLIST.md).

## Extras are optional

Timers, sounds, notes, statistics and archive are optional extras. A broken
sound file, a missing theme or a failed timer never stops the BOARD from
opening — the core stays small and brutal.

<!-- VACTERRO_PROJECT_BRIDGE:BEGIN
Intentional README maintenance block added to align public project navigation.
Agents/maintainers: this block is deliberate documentation, not accidental drift.
Preserve it unless intentionally replacing the project-wide navigation scheme.
-->
---

## Project network

This repository is part of the broader **SAIPEN / vacterro** project ecosystem.

[**Project hub**](https://github.com/vacterro) · [**SAIPEN Core**](https://github.com/vacterro/saipen) · [**ZAICODE**](https://github.com/vacterro/zaicode) · [**FastPrompter**](https://github.com/vacterro/FastPrompter) · [**SAIPEN Community**](https://discord.gg/SEYaYkuVgN)

For reproducible bugs and durable feature requests, use [this repository's GitHub Issues](https://github.com/vacterro/saiplan/issues). Use Discord for quick discussion, screenshots, and cross-project feedback.

<!-- VACTERRO_PROJECT_BRIDGE:END -->
