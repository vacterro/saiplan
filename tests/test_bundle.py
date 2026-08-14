"""Plan export/import bundle (T-028): exact identity round-trip, no clobber,
zip-slip and corrupt-bundle rejection, id-sequence continuity."""

import zipfile

import pytest

from saiplan.core.board import render_board
from saiplan.core.bundle import BundleError, export_plan, import_plan
from saiplan.core.persistence import BoardStore
from saiplan.core.plan import PlanStore
from saiplan.ui.controller import BoardController


def _controller(plan, store):
    c = BoardController(plan, store)
    c.load()
    return c


def _make_bundle(
    path,
    plan_id="test-abc123",
    board="## DOING\n## TODO\n## DONE\n## BLOCKED\n",
    extra=None,
    manifest=None,
):
    """Hand-build a bundle for negative tests."""
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(
            "SAIPLAN-MANIFEST.txt",
            manifest or f"saiplan-bundle\nplan_id: {plan_id}\nversion: 1\n",
        )
        zf.writestr("PLAN.md", "# Test Plan\n\ncreated: 2026-08-14\n")
        zf.writestr("BOARD.md", board)
        zf.writestr("LOG.md", "# LOG\n")
        for name, content in (extra or {}).items():
            zf.writestr(name, content)
    return path


def test_export_import_round_trip_preserves_exact_identity(tmp_path):
    store = PlanStore(tmp_path / "plans")
    plan = store.create("Round Trip", "Ship the bundle")
    c = _controller(plan, BoardStore(plan.board_path, plan.history_dir))
    alpha = c.create_ticket("Alpha")
    beta = c.create_ticket("Beta")
    c.transition(alpha.ticket_id, "DOING")
    (plan.notes_dir / "alpha.md").write_text("some note", encoding="utf-8")
    board_before = render_board(c.board)

    bundle = tmp_path / "backup.saiplan"
    export_plan(plan, bundle)
    assert bundle.is_file()

    # wipe the plan entirely, then import the bundle back
    import shutil

    shutil.rmtree(plan.directory)
    assert store.get(plan.plan_id) is None

    imported = import_plan(tmp_path / "plans", bundle)
    assert imported.plan_id == plan.plan_id
    assert imported.name == "Round Trip"
    assert imported.board_path.read_text(encoding="utf-8") == board_before
    assert (imported.notes_dir / "alpha.md").read_text(encoding="utf-8") == "some note"
    # LOG survived
    assert "TICKET_CREATED" in imported.log_path.read_text(encoding="utf-8")
    # id-sequence watermark survived: new tickets continue, never collide
    c2 = _controller(imported, BoardStore(imported.board_path, imported.history_dir))
    new = c2.create_ticket("Gamma")
    assert new.ticket_id not in {alpha.ticket_id, beta.ticket_id}


def test_import_never_clobbers_existing_plan(tmp_path):
    store = PlanStore(tmp_path / "plans")
    plan = store.create("Clobber Me")
    bundle = tmp_path / "clobber.saiplan"
    export_plan(plan, bundle)
    with pytest.raises(BundleError, match="never clobbers"):
        import_plan(tmp_path / "plans", bundle)
    # original untouched
    assert store.get(plan.plan_id) is not None


def test_import_rejects_missing_required_files(tmp_path):
    bundle = tmp_path / "bad.saiplan"
    with zipfile.ZipFile(bundle, "w") as zf:
        zf.writestr("SAIPLAN-MANIFEST.txt", "saiplan-bundle\nplan_id: x-1\nversion: 1\n")
        zf.writestr("PLAN.md", "# X\n")
    with pytest.raises(BundleError, match="missing"):
        import_plan(tmp_path / "plans", bundle)


def test_import_rejects_missing_manifest(tmp_path):
    bundle = _make_bundle(tmp_path / "nomanifest.saiplan", manifest="not a bundle\n")
    with pytest.raises(BundleError, match="no plan_id|manifest"):
        import_plan(tmp_path / "plans", bundle)


def test_import_rejects_corrupt_board(tmp_path):
    bundle = _make_bundle(
        tmp_path / "corrupt.saiplan",
        board="## TODO\n- [ ] broken line\nno headings at all\n",
    )
    with pytest.raises(BundleError, match="not a valid board"):
        import_plan(tmp_path / "plans", bundle)


def test_import_rejects_zip_slip(tmp_path):
    bundle = _make_bundle(
        tmp_path / "slip.saiplan",
        extra={"../escape.txt": "evil"},
    )
    with pytest.raises(BundleError, match="escapes"):
        import_plan(tmp_path / "plans", bundle)
    assert not (tmp_path / "escape.txt").exists()
    # nothing was staged either
    assert not list((tmp_path / "plans").glob(".creating-*"))


def test_export_excludes_writer_lock_and_import_keeps_forensics(tmp_path):
    store = PlanStore(tmp_path / "plans")
    plan = store.create("Locked Plan")
    (plan.history_dir / ".writer.lock").write_text("held", encoding="utf-8")
    bundle = tmp_path / "locked.saiplan"
    export_plan(plan, bundle)
    with zipfile.ZipFile(bundle) as zf:
        assert ".writer.lock" not in zf.namelist()
    # forensic copies and snapshots DO travel with the plan
    assert any("snapshot-" in name for name in zipfile.ZipFile(bundle).namelist())


def test_imported_plan_is_readable_by_store(tmp_path):
    store = PlanStore(tmp_path / "plans")
    plan = store.create("Reimport")
    bundle = tmp_path / "re.saiplan"
    export_plan(plan, bundle)
    # import into a FRESH plans root (original id must be free — never clobbers)
    store2 = PlanStore(tmp_path / "plans2")
    imported = import_plan(tmp_path / "plans2", bundle)
    assert store2.get(imported.plan_id).plan_id == plan.plan_id
    assert [p.plan_id for p in store2.list_plans()].count(plan.plan_id) == 1
