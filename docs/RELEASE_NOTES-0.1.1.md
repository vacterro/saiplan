# SAIPLAN 0.1.1 — release notes

**Status:** release candidate — waiting only on the T-011 human GUI walk
(`docs/RELEASE_WALK.md`, ~10 minutes). Once walked, tag `v0.1.1` at HEAD and
attach the two artifacts below.

SAIPLAN is a lightweight portable Windows planner with SAIPEN-style
discipline for ordinary humans: write what needs doing, make the plan
explicit, do the next thing. Plain Markdown files are the authority — no
database, no cloud, no account, no telemetry. The whole app moves with its
folder (USB stick included).

## What's new in 0.1.1

**Data integrity (the core promise):**
- Strict BOARD contract — a board with any structural error is never silently
  "fixed"; corrupt bytes are preserved byte-for-byte before validated
  snapshot recovery.
- Transactional mutations — a refused save leaves memory, disk, undo and the
  semantic LOG untouched.
- Conflict resolution preserves BOTH sides; external edits are never silently
  overwritten.
- Single-writer contract — the second instance hands off with a nonce + ACK
  and can never become a second writer.
- Persisted undo/redo across restart; trash restores exact identity; rotating
  validated snapshots.

**New in this release:**
- **Recovery dialog** — browse snapshots and forensic corrupt/pre-restore
  copies, preview, and restore any validated snapshot; the current board is
  backed up byte-exact first and undo stays available.
- **Plan export/import** — any plan is one portable `.saiplan` file (board,
  notes, history and identity travel together); import restores exact
  identity and never overwrites an existing plan.
- **Ticket attachments** — attach files to tickets (Unicode-safe names,
  never overwritten); deleting or reopening a ticket never loses them;
  bundles carry them.
- **Reproducible packaging** — pinned build environment, source-identity gate
  (`BUILD-SOURCE.sha256`), `MANIFEST.sha256`, junk gate, and clean
  source/portable packages (`scripts/package_*.ps1`).

**Quality:** 322 tests (316 platform-neutral + 6 subprocess), ruff clean,
Nuitka portable build + launch/handoff smoke.

## Install / run

No installer. Download `SAIPLAN-0.1.1-windows-x64.zip`, extract anywhere
writable (e.g. `C:\SAIPLAN\` or a USB stick), and run `SAIPLAN.exe`. Data,
themes and sounds live next to the exe and move with the folder. If the
folder is read-only, SAIPLAN refuses to start rather than scatter data.

## Verify

```powershell
# extract, then from the folder:
SAIPLAN.exe                              # first-run: create a plan
# build-from-source verification:
python -m pytest -q                      # 322 passed
python -m pytest -q -m "not subprocess"  # 316 passed
python -m pytest -q -m subprocess        # 6 passed
python -m ruff check src tests
python scripts/verify_release.py portable --source . --root dist/SAIPLAN
```

## Checksums (SHA-256)

```
1c39eaec109b418edb7ed8858f2f1dfcf9c93337258849ee204d636505dd3f9e  SAIPLAN-0.1.1-windows-x64.zip
3c8e6c4f72d9e4ecb0f8f6885abf02dee593e48ebc5db944b5cbffe5cbe10076  SAIPLAN-0.1.1-source.zip
```

## Artifacts

- `dist/SAIPLAN-0.1.1-windows-x64.zip` — portable folder (48 MB): `SAIPLAN.exe`
  + `themes/` (16) + `sounds/` (414) + `MANIFEST.sha256`.
- `dist/SAIPLAN-0.1.1-source.zip` — clean source tree, pinned build
  dependencies, `scripts/package_*.ps1` to rebuild everything.

## Release process used

Walked `docs/RELEASE_CHECKLIST.md` (spec §24); pass report in
`docs/RELEASE_PASS-0.1.1.md`. History: T-018..T-030 closed; T-011 (human GUI
walk) is the only open item.
