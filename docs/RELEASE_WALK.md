# 10-minute human walk (T-011)

The machine lanes are already green (`docs/RELEASE_PASS-0.1.1.md`). This is
the ONLY human work left before 0.1.1 can be tagged. Start a timer, do the
steps in order. If something surprises you, write it down and open a ticket —
do not release with a known-open item.

Setup (1 min): copy `dist/SAIPLAN` to a USB stick or a fresh folder on
another PC and launch `SAIPLAN.exe` from there. Everything below happens in
that copy.

1. **First run (1 min)** — create a plan, type one task, Enter. It lands in
   TODO. Close the app, relaunch: the plan and the board come back.
2. **Lifecycle (2 min)** — Ctrl+Enter (start) → Ctrl+D (done) → Ctrl+B with a
   reason (block) → Ctrl+Shift+R (reopen). Open `data/plans/<id>/BOARD.md` in
   Notepad: checkbox `[x]` matches the column (plain files, no SAIPLAN needed).
3. **Inspector (2 min)** — click the ticket: change priority, tags, due; add
   a checklist item; type into Details; click **Notes** and add `[[S-1]]`;
   click **Attach…** and pick any small file, then **Open** — it opens in the
   default app. Press `Space` to start/stop the ticket timer.
4. **Safety (2 min)** — Ctrl+Z, restart, Ctrl+Shift+Z (undo survives
   restart). Delete the ticket, open **Trash**, restore it — same id, note
   and attachment still there. In Notepad edit BOARD.md, save, return to
   SAIPLAN: the external-edit banner appears; reload it.
5. **Themes (2 min)** — Settings → theme: flip through all 16. Text must stay
   readable in every one; Golden Vintage is the default on restart.
6. **Portability (1 min)** — while the app runs, copy the folder again and
   launch the copy: it opens the same data and the second instance hands off
   (a message flashes and it exits). Export the plan (**Export plan…**), then
   **Import Plan…** the file into a third copy: the same plan id comes back.

Done. If all six passed, tick the `HUMAN` items in
`docs/RELEASE_PASS-0.1.1.md` (4, 10, 12, 17, 22–25, 27, 28) and the release
can be tagged (`git tag v0.1.1`).
