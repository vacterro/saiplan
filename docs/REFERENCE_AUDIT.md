# SAIPLAN — Reference Audit

Audited 2026-08-13 against the CURRENT HEAD of each repository (local clones
synced to `origin/HEAD` via `git fetch`; FastPrompter was re-cloned pristine
because its local worktree carried uncommitted edits).

## Audited HEAD commits

| Repo | Commit | Tag/version | Source |
|---|---|---|---|
| FastPrompter | `e88007cf80bb6ba3bdab119259e4cad4f4f35dc3` | release v0.8.36 | github.com/vacterro/FastPrompter |
| SAIPENVIEW | `5b18d1710901485961c1a44a995140bcc549b40a` | — | github.com/vacterro/saipenview |
| SAIPEN | `a477d64170dcd956c20609625cd73765d03a034c` | v7.223.12 | github.com/vacterro/saipen |
| Wintage | `1b915feecbaf1a6393ecc0650045781b8c7fe10f` | v1.26.8 | github.com/vacterro/Wintage |

> HEAD note (2026-08-13): local FastPrompter worktree later advanced to
> `ca790f8` ("chore(audit): Fourth-pass boundary audit fixes (P0 & P1)", ahead
> of `origin/main`). That commit only adds `tests_smoke/` boundary tests and
> touches `main.py`/`file_container.py`/`watcher_mixin.py` shutdown serialization;
> it changes no audited mechanism (atomic write, backup, timers, sounds,
> hotkeys, single instance). Audit above stands against the released tag
> `e88007c` (v0.8.36), which is `origin/main` HEAD.

Audit principle: harvest MECHANISMS, not applications. Nothing below is copied
wholesale; each row records what SAIPLAN reuses, adapts, or rejects and why.

---

## Compact matrix

| SOURCE | MECHANISM | REUSE | ADAPT | REJECT | REASON |
|---|---|---|---|---|---|
| FastPrompter | portable path model (exe-adjacent `data/`, writable probe, `%LOCALAPPDATA%` fallback) | x | x | | SAIPLAN: exe-local `data/`; read-only dir must fail loudly / offer alternate writable root — no silent AppData scatter (spec §10) |
| FastPrompter | atomic write: temp + flush + fsync + `os.replace` | x | | | Same primitive in SAIPEN `codec.write_document`; adopt as canonical SAIPLAN writer base |
| FastPrompter | validated `.bak`: copy to temp, validate, then swap; pre-connect startup backup; throttle advances only on success | x | x | | .bak never trusted unvalidated; "empty/corrupt new state must never replace healthy backup" is FastPrompter's `validate_database` idea moved to plain text |
| FastPrompter | portable backup snapshot: temp dir + `_COMPLETE` marker written LAST + atomic publish with rollback sibling + 7-day retention + 120s throttle | x | x | | Direct model for SAIPLAN `.history` rotation + mirror; human-readable `.md` snapshots |
| FastPrompter | single instance: Windows named mutex (liveness = process, not ACK) + token-authenticated QLocalServer handoff, startup grace | x | | | Mutex authoritative; IPC only for "show existing window". Session-global name = one writer per session |
| FastPrompter | crash logging: rotating `crash.log` + unhandled-exception hook writing full traceback | x | x | | SAIPLAN keeps debug/crash logs under `logs/`, separate from semantic LOG.md |
| FastPrompter | undo | | x | | FastPrompter undo is IN-MEMORY snapshot stacks (data_undo_stack/redo_stack, cap 50 / 20MB) + Qt text undo. NOT persisted. SAIPLAN spec demands persisted undo across restart → SAIPLAN invents its own (JSONL op-log in `.history/`) |
| FastPrompter | trash / delete | | x | | FastPrompter folder delete is a plain filesystem delete. SAIPLAN uses recoverable `.history/trash.jsonl` records; delete never destroys ticket identity. |
| FastPrompter | timer model (`core/timers.py`): absolute wall-clock target, ISO serialization, corrupt entries skipped, repeat `advance()` loops into future, snooze always later, temperature color | x | x | | SAIPLAN ticket timer additionally records sessions into TIMELOG.jsonl; monotonic during process, wall-clock persisted |
| FastPrompter | Pomodoro (`core/pomodoro.py`): elapsed-time driven, pause/resume/skip, phase handoff, alarm_pending, restart does NOT lie about run state | x | | | Same engine shape; Qt-free |
| FastPrompter | sound: recursive wav discovery (414 files, 21.8 MB), per-event map file/enabled/volume, stale-name heal on load, `QSoundEffect` OR `winsound` fallback, WAV sample rescaling for volume, preview bypasses toggles | x | x | | Copy library as assets, dynamic enumerate (no hardcoded count); event set re-mapped for SAIPLAN events; missing/corrupt file must never crash |
| FastPrompter | hotkeys: `RegisterHotKey` via ctypes, layout-aware `VkKeyScanW`, shifted-symbol→base-key mapping | x | | | Global hotkeys for timer/status; in-app shortcuts via Qt |
| FastPrompter | scaling: unified 0.5–1.5 scale, font floors (8pt), per-button box budget, label-fit enforcement | x | | | Simpler: one zoom factor on base font + QSS px values; skip per-button ratchet complexity |
| FastPrompter | theme loading (`theme/themes.py`) | | x | | REJECTED as SAIPLAN theme source. Hand-built QSS dict, no validation, values scattered in source. Wintage JSON registry supersedes it |
| FastPrompter | sound settings + timer dialogs, tray, ctrl+q window positioning | | x | | Harrow the patterns (tray = optional, ctrl+q = optional) in Wave 4/6 |
| FastPrompter | SQLite settings store | | | x | Dual-authority with plain files forbidden by spec §2. SAIPLAN: BOARD.md canonical, JSON config |
| FastPrompter | watcher subsystem (CDP, agent skills) | | | x | Out of scope — no agent watching |
| Wintage | canonical `themes/*.json` registry (16 packs) | x | | | Copy all 16 JSONs verbatim as the SAIPLAN theme library |
| Wintage | 21-token schema (`theme-schema.json` / `theme-schema.js`) | x | | | ONE registry, ONE token schema; validation test = every shipped theme carries all 21 |
| Wintage | pack validation: slug lowercase-alnum, filename==slug, unique slug/label, no apostrophe in label, tokens all `#rrggbb` | x | x | | Add: Golden Vintage is default + fallback on unknown/corrupt |
| Wintage | WCAG AA gate: textPrimary/textSecondary/link vs backgroundSoft ≥ 4.5:1 | x | | | Reuse exact relative-luminance formula |
| Wintage | Win95 grammar: square corners, 2px bevel (light top-left / dark bottom-right), raised buttons, sunken fields, pressed=inverted bevel, zero radius, no animations | x | | | Enforced in SAIPLAN QSS generator |
| Wintage | multi-target generator (browser/electron/obsidian/windows/vscode/obs) | | | x | Not SAIPLAN's problem |
| SAIPENVIEW | BOARD parser: `- [ ] T-### desc | field: v`; escaped `\|`; strict grammar; duplicate single-valued field = malformed; checkbox must agree with section | x | x | | Adopt grammar; SAIPLAN adds human fields (title/due/priority/tags/estimate) beyond SAIPEN's closed set |
| SAIPENVIEW | ticket identity `T-###` never reused; next id = max over BOARD + LOG | x | | | SAIPLAN: monotonic id per plan, persisted, survives rename/drag/restart |
| SAIPENVIEW | write coordinator: per-root RLock + SelfWriteRegistry (fingerprint + TTL) so watcher attributes app writes vs external | x | x | | SAIPLAN: same causal model for external-edit detection (content hash/mtime) |
| SAIPENVIEW | ExternalChangeRegistry: unresolved external writes persist, only explicit acknowledge clears | x | | | Direct model for "externally edited → detect, reload/merge/conflict copy, never silent overwrite" |
| SAIPENVIEW | textio: BOM sniff, bomless UTF-16 detection, encoding-preserving decode/encode, atomic write preserves mode | x | | | Adopt; SAIPLAN writes its own plain UTF-8 files so this is mostly for READING foreign boards |
| SAIPENVIEW | config: exe-adjacent `config.json`, defaults + merge, atomic temp+replace | x | | | Same |
| SAIPENVIEW | file watcher: watchdog, watch only active `.saipen/`, track only STATE/BOARD/LOG, per-file debounce, handle os.replace temp-rename | x | x | | SAIPLAN watches current plan's BOARD.md (+ plans dir); per-file debounce 200ms |
| SAIPENVIEW | single-instance + tray + global hotkeys | x | | | FastPrompter mutex model is stronger; use that |
| SAIPENVIEW | themes (runtime CSS var swap) | x | x | | SAIPLAN: Qt QSS re-render from token registry at runtime; default differs (Golden Vintage) |
| SAIPENVIEW | agent engines (codex/claude/opencode/...) | | | x | Explicitly out of scope (spec §15) |
| SAIPENVIEW | multi-home scanner (auto .saipen discovery across drives) | | | x | SAIPLAN: one data root, explicit plan list |
| SAIPEN | BOARD contract: 4 sections, checkbox==section, ticket never under two headings, ID never reused | x | x | | Core of SAIPLAN BOARD.md; section order DOING/TODO/DONE/BLOCKED kept |
| SAIPEN | `needs:` dependency field; workable = open TODO, no blocker, all needs DONE | x | | | SAIPLAN dependencies = same semantics |
| SAIPEN | blocker rule: non-empty `blocker:` exactly under BLOCKED; block/unblock atomic move + set/remove field | x | x | | Same; SAIPLAN unblock also requires stated decision |
| SAIPEN | claim pair `owner`/`claim_time`, 15-min liveness | | x | | Single-user app: claim pair optional; only need started timestamp |
| SAIPEN | cycle/dangling dependency handling: move to BLOCKED with `blocker: dependency cycle: ...`, LOG `DEC` | x | | | SAIPLAN "Plan Review" detects + warns, advises not blocks |
| SAIPEN | write-ahead journal: PREPARED→APPLYING→VERIFIED→COMMITTED, staged bytes + before/after hashes, recovery preflight blocks mutation | x | x | | Full journal too heavy for single-user local app; SAIPLAN uses atomic write + backup + conflict detection instead |
| SAIPEN | checkpoint write order LOG→BOARD→STATE (STATE = commit pointer) | x | | | SAIPLAN: write BOARD atomically, then LOG append; BOARD is authority |
| SAIPEN | `verify:` completion criterion on tickets; DONE requires verify trace | x | x | | SAIPLAN optional `done-when` field; review warns on missing where applicable — never blocks |
| SAIPEN | next_action discipline (5 prefixes, WAIT categories) | | x | | Internal agent vocabulary. SAIPLAN exposes "next action" per ticket as plain field |
| SAIPEN | surgical decomposition / goal→tickets planning rules | x | x | | "Break down" wizard: GOAL → constraints → DoD → atomic tasks → deps → verify → order |
| SAIPEN | LOG taxonomies + event grammar | x | x | | SAIPLAN semantic LOG events (PLAN_CREATED etc.) — own vocabulary |
| SAIPEN | encoding-preserving Document codec (BOM/newline/final-newline) | x | | | Reuse for foreign-file read safety |

## Key numbers captured at audit time

- FastPrompter sound library: **414 `.wav` files, 21.8 MB** (incl. `cs_style/` 3 files). No hardcoded count — dynamic discovery.
- Wintage theme packs: **16** (`themes/*.json`): antigravity, claudecode,
  codenomad, custom, dracula, fpdefault, freebuff, golden, goldendefault,
  goldenvintage, klite, nord, oled, solarized, vintageclassic, vintagedark.
  Default for SAIPLAN = **Golden Vintage** (`goldenvintage`).
- Wintage schema: **21 tokens** + 3 WCAG text roles (textPrimary, textSecondary,
  link vs `backgroundSoft`, floor 4.5:1).
- SAIPEN required STATE fields: 9 (phase, task, next_action, blocker, agent,
  updated, mode, saipen_version, transition_from) — SAIPLAN does not imitate
  STATE.md at all (decision in ARCHITECTURE.md).
- SAIPEN BOARD soft cap: ~16 KB warning; DONE section scrubbed by CLEAN.

## Design decisions forced by audit

1. **BOARD.md is canonical and stays plain text.** Both SAIPEN and SAIPENVIEW
   prove a strict line grammar round-trips losslessly with escaped pipes and
   surgical field edits (`set_ticket_field` / `remove_ticket_field` preserve
   every other byte). SAIPLAN reuses this discipline.
2. **External-edit safety borrows SAIPENVIEW's causal model, not polling.**
   Track content hash + mtime of BOARD.md; on load/refresh compare; on
   mismatch reload + merge or conflict copy — never silent overwrite.
3. **Undo must be invented, not ported.** FastPrompter has no persisted undo.
   SAIPLAN `.history/undo.jsonl` = append-only command log; replay to restore.
4. **Trash must be invented, not ported.** FastPrompter's delete is permanent.
5. **Timers: two distinct engines** like FastPrompter — deadline timers
   (absolute wall-clock, survives restart) and stopwatch/Pomodoro (elapsed-time
   driven, run state does NOT survive restart). Ticket timers = deadline-style
   session recorder into TIMELOG.jsonl.
6. **Themes come from Wintage JSONs, never from FastPrompter's `themes.py`.**
   The 21-token schema + WCAG gate are the contract; FastPrompter's hardcoded
   QSS strings are the anti-pattern (I12).
