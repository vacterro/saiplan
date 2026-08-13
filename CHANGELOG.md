# Changelog

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
