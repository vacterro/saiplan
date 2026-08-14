# Release pass report — 0.1.1 (2026-08-14, UTC)

Filled-in run of [RELEASE_CHECKLIST.md](RELEASE_CHECKLIST.md) against commit
`a383268` + the T-029/T-030 working-tree wave. Statuses: `PASS` (verified
this pass), `auto` (covered by an automated test, no human needed), `HUMAN`
(still requires the on-screen human — T-011).

| # | Item | Status | Evidence |
|---|------|--------|----------|
| 1 | Portable build (bootstrap + package_portable) | PASS | `package_portable.ps1` → `PASS dist/SAIPLAN-0.1.1-windows-x64.zip` (warm-cache Nuitka rebuild) |
| 2 | Verify portable artifacts (identity + manifest) | PASS | `verify_release.py portable` → 485 files; BUILD-SOURCE matches current source; 16 themes + 414 sounds hash-matched |
| 3 | Source package + junk gate | PASS | `package_source.ps1` → versions agree, required files present, junk gate clean |
| 4 | Fresh-machine copy launch | HUMAN | needs a human on another machine/USB (T-011) |
| 5 | Full pytest | PASS | `pytest -q` → 322 passed |
| 6 | Exact lanes | PASS | 316 neutral + 6 subprocess = 322, no overlap |
| 7 | ruff check + format | PASS | clean; 59 files formatted |
| 8 | Frozen exe smoke | PASS | copied folder + `SAIPLAN_AUTOQUIT_MS=1500` offscreen → exit 0, log `exit rc=0` |
| 9 | Single instance / handoff | PASS | second exe → `handoff ACK; exiting`, exit 0; first stays writer |
| 10 | First-run create plan + quick-add | auto + HUMAN | flow covered by `test_create_plan_then_ticket_flow`; visual feel needs human |
| 11 | Restart keeps board | auto | `test_restart_state_correct` |
| 12 | TODO→DOING→DONE + BOARD.md `[x]` | auto | controller lifecycle tests; BOARD.md readability is inherent (I3) |
| 13 | Block + reopen with reason | auto | `test_unblock_and_reopen_emit_distinct_events` |
| 14 | Single-focus refusal | auto | `test_controller_enforces_single_focus...` |
| 15 | Delete → trash → restore, same id + notes/attachments | auto | `test_trash_and_restore_ui`; attachments survival tests |
| 16 | All inspector fields persist instantly + across restart | auto | field-save + restart tests |
| 17 | Notes with `[[S-1]]` links + attach/open/remove | auto + HUMAN | notes/attachments tests; "Open with default app" is HUMAN |
| 18 | Ticket timer writes TIMELOG.jsonl | auto | timer tests |
| 19 | Undo/redo across restart | auto | `test_undo_redo_across_restart` |
| 20 | External-edit banner, no silent overwrite | auto | conflict tests (`test_two_sequential_conflicts_both_surface`) |
| 21 | Recovery browse/preview/restore + backup | auto | T-027 recovery tests + smoke |
| 22 | Timers panel (countdown/stopwatch/pomodoro) | auto + HUMAN | timer/Qt tests; feel needs human |
| 23 | Sounds preview/toggle/volume, corrupt-file safe | auto + HUMAN | sound tests; preview needs human |
| 24 | All 16 themes apply, readable, Golden Vintage default | auto + HUMAN | `test_themes` → 16 passed, WCAG AA; on-screen look needs human |
| 25 | Copy folder → same data; second instance hands off | auto | exe handoff smoke; other-machine check is HUMAN |
| 26 | Export/import exact identity, no clobber | auto | `test_bundle.py` (8 tests) + UI handlers |
| 27 | Visual polish per theme | HUMAN | |
| 28 | Shortcuts on real non-Latin layout | auto + HUMAN | `test_platform` fixed-VK tests; real-keyboard feel needs human |
| 29 | Final gates + tag + publish | HUMAN | release decision; artifacts ready in `dist/` |

## What actually remains for the human (T-011)

1. Fresh-machine/USB copy launch and basic first-run (items 4, 25).
2. Visual/feel pass in the real GUI, especially theme switching (24, 27) and
   drag/drop + keyboard feel (10, 12, 22, 23, 28).
3. Confirm "Open attachment" launches the default app (17).
4. Cut the tag, publish the two `dist/` zips (29) — after the T-029/T-030 wave
   is committed.

Nothing is known-open on the machine lane: every `[auto]` item and every
test-covered `[manual]` item passed against the current tree.
