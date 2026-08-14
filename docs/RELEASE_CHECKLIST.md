# Release checklist (spec §24 definition of done)

Every release walks this checklist. Items are tagged:

- `[auto]` — machine-verifiable: the exact command is given; the gate either
  passes or the release is not made. These are the agent's lanes.
- `[manual]` — needs a human at the machine (visuals, feel, real keyboard,
  all-16-theme switching). This is the T-011 human pass, reduced to a guided
  walk.

Truth rule: if a `[manual]` item cannot be completed, the release waits — no
release is shipped with a known-open item. A `[manual]` item is only ticked by
the human who performed it.

---

## 0. Fresh portable copy

1. `[auto]` Build from a clean checkout:
   `powershell -File bootstrap-build-env.ps1`, then
   `powershell -File scripts/package_portable.ps1` (requires a clean tracked
   worktree; uses `-AllowDirty` only for pre-commit verification).
2. `[auto]` Verify artifacts:
   `python scripts/verify_release.py portable --source . --root dist/SAIPLAN`
   → `BUILD-SOURCE.sha256` matches the current source identity,
   `MANIFEST.sha256` matches the dist (485 files), 16 themes + 414 sounds
   hash-match the source.
3. `[auto]` Source package: `powershell -File scripts/package_source.ps1` →
   junk gate passes, required files present, versions agree
   (VERSION == pyproject == `__version__`).
4. `[manual]` Copy `dist/SAIPLAN` to a writable location that is NOT the build
   machine's checkout (a USB stick or a fresh folder on another PC). Launch
   `SAIPLAN.exe` from there. The app opens to the first-run "Create Plan"
   flow and `data/` is created next to the exe.

## 1. Automated gates (agent)

5. `[auto]` Full suite: `python -m pytest -q` → all green (322 as of 0.1.1).
6. `[auto]` Exact lanes: `python -m pytest -q -m "not subprocess"` and
   `python -m pytest -q -m subprocess` → counts sum to the full run with no
   overlap (316 + 6 = 322 as of 0.1.1).
7. `[auto]` Lint + format: `python -m ruff check src tests` and
   `python -m ruff format --check src tests` → clean.
8. `[auto]` Frozen exe smoke: run the copied folder with
   `SAIPLAN_AUTOQUIT_MS=1500` + `QT_QPA_PLATFORM=offscreen` → exit code 0,
   `logs/saiplan.log` shows `start` and `exit rc=0`.
9. `[auto]` Single instance: launch the exe twice — the second instance
   prints `second instance; handoff ACK; exiting` and exits 0 in about a
   second while the first stays alive; killing the first lets the next start
   become the writer. (Also covered by `tests/test_single_instance.py`.)

## 2. Human GUI walk (T-011)

Each item: do the action, check the expectation, tick. If anything surprises
you, capture the exact steps and open a ticket — do not release.

### 2.1 First run
10. `[manual]` Create a plan: name + one-sentence objective. Expect a focused
    quick-add box — typing a task and pressing Enter puts it in **TODO**
    (I2, I15). Check the plan appears in the left dock.
11. `[manual]` Close and relaunch the exe. Expect the plan reopens on the
    same board — nothing is lost across restart (I13).

### 2.2 Board lifecycle
12. `[manual]` Move the ticket TODO → **DOING** (drag or Ctrl+Enter) → **DONE**
    (Ctrl+D). Expect the column shows it, the inspector reflects the status,
    and `BOARD.md` in `data/plans/<id>/` shows the checkbox `[x]` (I3: plain
    files readable without SAIPLAN).
13. `[manual]` Block a ticket (Ctrl+B, add a reason) and reopen it
    (Ctrl+Shift+R). Expect BLOCKED shows the reason; reopen returns it to TODO.
14. `[manual]` With single-focus on, try to start a second ticket while one is
    DOING. Expect a refusal message, not a silent second DOING.
15. `[manual]` Delete a ticket (Delete), check the Trash dialog, restore it.
    Expect it returns with the SAME id and its notes/attachments intact (I6).

### 2.3 Inspector
16. `[manual]` Edit every field: title, priority, due, tags, needs,
    estimate, done-when, details, checklist. Expect each change persists
    immediately (no Save button) and survives a restart.
17. `[manual]` Add a note (Notes button) with `[[S-1]]` links; add a file
    attachment (Attach…); open it with the default app (Open); remove it
    (Remove → it lands in `.history/attachments-trash/`).
18. `[manual]` Start/pause the ticket timer (Space). Expect the tracked
    session appears in `TIMELOG.jsonl`.

### 2.4 Recovery, undo, conflicts
19. `[manual]` Make an edit, then Ctrl+Z / Ctrl+Shift+Z across a restart.
    Expect undo/redo survive (persisted op-log).
20. `[manual]` Open `BOARD.md` in a text editor, edit it, save, and return to
    SAIPLAN. Expect the external-edit banner; resolve by reloading or keeping
    the local version — never a silent overwrite (I5).
21. `[manual]` Recovery: make a few saves, open **Recovery**, preview a
    snapshot, restore it. Expect a `restore-before` backup appears and undo
    brings the previous board back.

### 2.5 Timers, sounds, themes
22. `[manual]` Open **Timers**: countdown, stopwatch, Pomodoro. Expect pause/
    resume/skip work and phases survive a restart (I13).
23. `[manual]` Open **Sounds**: preview events, toggle a few, set volume.
    Expect no crash when a file is missing or corrupt (I8).
24. `[manual]` Switch through ALL 16 themes one by one (Settings → theme).
    Expect every theme applies, text stays readable (WCAG AA), and Golden
    Vintage is the default (I11/I12).

### 2.6 Portability & data
25. `[manual]` While the app runs, copy the whole folder somewhere else and
    launch the copy — expect it opens the same data (I14: data/assets/config
    move together) and the second instance hands off instead of writing.
26. `[manual]` Export the open plan (**Export plan…**) and import it into a
    fresh copy (**Import Plan…**). Expect EXACT identity (same plan id) and
    the original plan untouched.

## 3. Polish pass (visual, human judgment)

27. `[manual]` Walk TODO → DOING → DONE again in each theme for a minute.
    Look for: clipped text, unreadable contrast, misaligned controls, window
    resize behavior, dock collapse/float, and the first-run focus order.
28. `[manual]` Check keyboard shortcuts from the README work with a real
    (non-Latin-safe) layout: Ctrl+N, Ctrl+Shift+N, Ctrl+F, Ctrl+Z,
    Ctrl+Shift+Z, Ctrl+1..4, Delete, Space.

## 4. Ship

29. `[auto]` Re-run item 5–8 once more on the final tree, then tag the
    release (`git tag v<version>`), write the CHANGELOG entry, and publish
    the two artifacts from `dist/`.

---

Nothing below this line is required for release; it documents why the
checklist is shaped this way.

- Every `[auto]` item exists as a test or a script (`tests/`,
  `scripts/verify_release.py`, `build_windows.ps1`) so the agent can re-run
  the whole machine lane in minutes.
- The `[manual]` items map 1:1 to product invariants I1–I15 pinned in
  `docs/ARCHITECTURE.md`; if an item feels like it "should be automated",
  that is a defect report, not a release blocker.
