"""Plan export/import as one portable file (T-028).

A bundle is a plain .zip (`.saiplan` extension) containing the plan's whole
directory — PLAN.md, BOARD.md, LOG.md, TIMELOG.jsonl, notes/, .history/ (undo,
trash, snapshots, id-sequence watermark) — plus a small manifest carrying the
immutable plan_id. Moving a plan between machines or into a backup is a single
file; importing restores EXACT identity when the original id is free.

Contracts:

- Import NEVER clobbers: if `plans/<plan_id>` already exists, import refuses.
- Extraction is transactional: staged under `plans/.creating-<uuid>/`,
  validated, then atomically renamed into place — a crash or a bad bundle
  leaves no partial plan (same discipline as PlanStore.create).
- Zip-slip is rejected: members with absolute paths or `..` components are
  refused before anything is written.
- A bundle whose BOARD.md does not parse structurally is rejected.
"""

from __future__ import annotations

import os
import shutil
import uuid
import zipfile
from pathlib import Path

from ..core.board import parse_board_detailed
from ..core.plan import Plan, PlanError, PlanStore, read_plan_md, validate_plan_id

BUNDLE_MANIFEST = "SAIPLAN-MANIFEST.txt"
BUNDLE_VERSION = "1"
_EXCLUDED_NAMES = {".writer.lock"}


class BundleError(ValueError):
    pass


def export_plan(plan: Plan, target: Path) -> Path:
    """Write the whole plan directory to one .saiplan bundle.

    The transient `.writer.lock` (held by a running process) is never bundled.
    Everything else — including the id-sequence watermark and snapshots — goes
    in, so an imported plan resumes exactly where it left off.
    """
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    temp_target = target.with_suffix(".zip.tmp")

    from ..core.persistence import BoardStore

    board_store = BoardStore(plan.board_path, plan.history_dir)
    fingerprint_before = board_store.read_raw().fingerprint

    try:
        with zipfile.ZipFile(temp_target, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr(
                BUNDLE_MANIFEST,
                f"saiplan-bundle\nplan_id: {plan.plan_id}\nversion: {BUNDLE_VERSION}\n",
            )
            for file in sorted(plan.directory.rglob("*")):
                if not file.is_file() or file.name in _EXCLUDED_NAMES:
                    continue
                zf.write(file, file.relative_to(plan.directory).as_posix())

        fingerprint_after = board_store.read_raw().fingerprint
        if fingerprint_before != fingerprint_after:
            raise BundleError("BOARD.md changed during export; aborting to prevent mixed state")

        # Validate the constructed bundle
        with zipfile.ZipFile(temp_target) as zf:
            if zf.testzip() is not None:
                raise BundleError("exported bundle is corrupt")
            _valid_members(zf)

        os.replace(temp_target, target)
    except Exception:
        try:
            temp_target.unlink()
        except OSError:
            pass
        raise
    return target


def read_bundle_plan_id(bundle: Path) -> str:
    """The immutable plan_id carried by the bundle manifest."""
    with zipfile.ZipFile(bundle) as zf:
        try:
            manifest = zf.read(BUNDLE_MANIFEST).decode("utf-8")
        except KeyError as exc:
            raise BundleError("not a SAIPLAN bundle (missing manifest)") from exc
        except (zipfile.BadZipFile, RuntimeError, UnicodeDecodeError) as exc:
            raise BundleError(f"unreadable bundle manifest: {exc}") from exc
    plan_id = None
    for line in manifest.splitlines():
        if line.startswith("plan_id: "):
            plan_id = line[len("plan_id: ") :].strip()
            break
    if not plan_id:
        raise BundleError("bundle manifest has no plan_id")
    try:
        validate_plan_id(plan_id)
    except PlanError as exc:
        raise BundleError(f"bundle manifest has invalid plan_id: {exc}") from exc
    return plan_id


def _valid_members(zf: zipfile.ZipFile) -> list[zipfile.ZipInfo]:
    """Reject zip-slip before writing: absolute members and `..` traversal
    are refused, no partial extraction happens."""
    members = []
    seen = set()
    total_size = 0
    for info in zf.infolist():
        name = info.filename.replace("\\", "/")
        if name.startswith(("/", "..")) or "/../" in name or name.endswith("/..") or name == "..":
            raise BundleError(f"bundle member escapes the plan folder: {info.filename!r}")
        if len(name) >= 2 and name[1] == ":" and name[0].isalpha():
            raise BundleError(f"bundle member contains windows drive letter: {info.filename!r}")
        if name in seen:
            raise BundleError(f"duplicate bundle member: {info.filename!r}")
        seen.add(name)
        if info.is_dir():
            continue
        total_size += info.file_size
        if total_size > 500 * 1024 * 1024:
            raise BundleError("bundle uncompressed size exceeds 500MB safety limit")
        members.append(info)
    return members


def import_plan(plans_dir: Path, bundle: Path) -> Plan:
    """Import a bundle into `plans_dir` with EXACT identity.

    Refuses (BundleError) when the plan already exists (never clobbers), when
    required files are missing, or when BOARD.md does not parse structurally.
    """
    plans_dir = Path(plans_dir)
    bundle = Path(bundle)
    plan_id = read_bundle_plan_id(bundle)
    final = plans_dir / plan_id
    if final.exists():
        raise BundleError(
            f"plan '{plan_id}' already exists; import refused (SAIPLAN never clobbers)"
        )
    with zipfile.ZipFile(bundle) as zf:
        names = set(zf.namelist())
        missing = [name for name in ("PLAN.md", "BOARD.md", "LOG.md") if name not in names]
        if missing:
            raise BundleError("bundle is missing: " + ", ".join(missing))
        board_text = zf.read("BOARD.md").decode("utf-8")
        _board, errors, _w = parse_board_detailed(board_text)
        if errors:
            raise BundleError(f"bundle BOARD.md is not a valid board: {errors[0]}")
        members = _valid_members(zf)
        if BUNDLE_MANIFEST not in names:
            raise BundleError("bundle is missing the manifest")

    staging = plans_dir / f".creating-{uuid.uuid4().hex}"
    try:
        staging.mkdir(parents=True)
        with zipfile.ZipFile(bundle) as zf:
            for info in members:
                target = staging / info.filename.replace("\\", "/")
                target.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(info) as src, open(target, "wb") as dst:
                    shutil.copyfileobj(src, dst)
        plan_md = staging / "PLAN.md"
        if not read_plan_md(plan_md)["name"]:
            raise BundleError("bundle PLAN.md has no plan name")
        os.replace(staging, final)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    plan = PlanStore(plans_dir).get(plan_id)
    if plan is None:
        raise BundleError("imported bundle did not produce a readable plan")
    return plan
