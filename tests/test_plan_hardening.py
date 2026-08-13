"""Plan identity / PLAN.md model / transactional create / archive identity
(spec 16/17/20): multilingual names, immutable plan_id, unknown-section
preservation, atomic plan creation, exact archive restore."""

import shutil

import pytest

from saiplan.core.plan import PlanStore, read_plan_doc, slugify
from saiplan.core.proposal import PlanProposal, TaskProposal
from saiplan.extras import archive


@pytest.fixture
def store(tmp_path):
    return PlanStore(tmp_path / "plans")


def test_multilingual_names_never_collapse(store):
    a = store.create("Русский план")
    b = store.create("日本語プラン")
    c = store.create("Eesti plaan")
    assert a.plan_id != b.plan_id != c.plan_id
    assert "Русский" not in a.plan_id  # slug component is ascii, that's fine
    # but the human name is preserved in PLAN.md
    assert store.get(a.plan_id).name == "Русский план"
    assert store.get(b.plan_id).name == "日本語プラン"


def test_plan_id_has_unique_suffix(store):
    a = store.create("Buy SSD")
    b = store.create("Buy SSD")
    assert a.plan_id != b.plan_id
    assert a.plan_id.startswith("buy-ssd-")
    assert b.plan_id.startswith("buy-ssd-")


def test_plan_doc_preserves_unknown_sections(store):
    plan = store.create("Doc", "The goal")
    plan.update_plan_doc(constraints="budget small", definition_of_done="boots")
    # append a human section the writer does not know about
    path = plan.plan_md_path
    text = path.read_text(encoding="utf-8")
    path.write_text(text + "\n## My Private Notes\nkeep this forever\n", encoding="utf-8")
    plan.update_plan_doc(name="Renamed")
    updated = path.read_text(encoding="utf-8")
    assert "## My Private Notes" in updated
    assert "keep this forever" in updated
    assert "## Objective" in updated and "The goal" in updated
    doc = read_plan_doc(path)
    assert doc.name == "Renamed"
    assert doc.sections["Constraints"] == "budget small"


def test_rename_preserves_unknown_sections(store):
    plan = store.create("Rename me", "objective text")
    path = plan.plan_md_path
    path.write_text(path.read_text(encoding="utf-8") + "\n## Custom\nxyz\n", encoding="utf-8")
    plan.update_plan_doc(name="Renamed")
    text = path.read_text(encoding="utf-8")
    assert "# Renamed" in text
    assert "## Custom\nxyz" in text
    assert store.get(plan.plan_id).name == "Renamed"


def test_plan_create_is_transactional(store, monkeypatch):
    """A failed create leaves no partial plan and no .creating- junk."""
    from saiplan.core import plan as plan_mod

    # normal create leaves no staging dirs behind
    store.create("Fine")
    assert list(store.plans_dir.glob(".creating-*")) == []
    # force a failure mid-build: the staging dir must be cleaned up
    calls = {"n": 0}
    real = plan_mod.atomic_write

    def flaky(path, text, **kw):
        calls["n"] += 1
        if calls["n"] == 3:
            raise OSError("simulated crash mid-create")
        return real(path, text, **kw)

    monkeypatch.setattr(plan_mod, "atomic_write", flaky)
    with pytest.raises(OSError):
        store.create("Doomed", "x")
    assert list(store.plans_dir.glob(".creating-*")) == []
    assert list(store.plans_dir.glob("doomed-*")) == []


def test_plan_created_event_logged(store):
    plan = store.create("Logged plan")
    log = plan.log_path.read_text(encoding="utf-8")
    assert "PLAN_CREATED" in log


def test_archive_restore_exact_identity(store):
    plan = store.create("buy-new-ssd", "goal")
    archived = archive.archive_plan(store.plans_dir, plan.plan_id)
    assert archived is not None
    assert not store.get(plan.plan_id)
    # original id survives round-trip exactly (never `buy` from a split)
    restored = archive.restore_plan(store.plans_dir, archived)
    assert restored is not None
    assert restored.name == plan.plan_id
    assert store.get(plan.plan_id) is not None
    assert store.get(plan.plan_id).name == "buy-new-ssd"


def test_archive_restore_with_collision(store):
    plan = store.create("collision-plan")
    archived = archive.archive_plan(store.plans_dir, plan.plan_id)
    # force a collision: a directory already exists under the original id
    (store.plans_dir / plan.plan_id).mkdir()
    restored = archive.restore_plan(store.plans_dir, archived)
    assert restored.name == f"{plan.plan_id}-restored"


def test_legacy_archive_without_metadata_restores_by_filename(store, tmp_path):
    plan = store.create("legacy-plan")
    root = archive.archive_root(store.plans_dir)
    shutil.move(str(plan.directory), str(root / f"{plan.plan_id}-2026-08-13"))
    archived = root / f"{plan.plan_id}-2026-08-13"
    restored = archive.restore_plan(store.plans_dir, archived)
    assert restored.name == plan.plan_id


def test_accept_proposal_atomic_and_updates_plan_md(store, tmp_path):
    from saiplan.core.persistence import BoardStore
    from saiplan.ui.controller import BoardController

    plan = store.create("Breakdown target")
    c = BoardController(plan, BoardStore(plan.board_path, plan.history_dir))
    c.load()
    proposal = PlanProposal(
        goal="Install new SSD",
        constraints="2280 slot",
        definition_of_done="boots from new drive",
        tasks=[
            TaskProposal("Buy SSD"),
            TaskProposal("Install", needs=["Buy SSD"]),
        ],
    )
    created = c.accept_proposal(proposal)
    assert len(created) == 2
    assert c.board.counts()["TODO"] == 2
    # needs resolved to real S-ids
    install = next(t for t in c.board.all_tickets() if t.title == "Install")
    first = created[0]
    assert install.get("needs") == first.ticket_id
    # PLAN.md updated
    md = plan.plan_md_path.read_text(encoding="utf-8")
    assert "## Constraints\n2280 slot" in md
    assert "## Definition of Done\nboots from new drive" in md
    assert "## Objective\nInstall new SSD" in md


def test_accept_proposal_invalid_creates_nothing(store, tmp_path):
    from saiplan.core.persistence import BoardStore
    from saiplan.ui.controller import BoardController, ControllerError

    plan = store.create("No partial")
    c = BoardController(plan, BoardStore(plan.board_path, plan.history_dir))
    c.load()
    bad = PlanProposal(goal="g", tasks=[TaskProposal("a", needs=["missing-task"])])
    with pytest.raises(ControllerError):
        c.accept_proposal(bad)
    assert c.board.counts()["TODO"] == 0
    assert not c.history.can_undo()


def test_accept_proposal_cycle_creates_nothing(store, tmp_path):
    from saiplan.core.persistence import BoardStore
    from saiplan.ui.controller import BoardController, ControllerError

    plan = store.create("Cycle plan")
    c = BoardController(plan, BoardStore(plan.board_path, plan.history_dir))
    c.load()
    cyc = PlanProposal(
        goal="g", tasks=[TaskProposal("a", needs=["b"]), TaskProposal("b", needs=["a"])]
    )
    with pytest.raises(ControllerError):
        c.accept_proposal(cyc)
    assert c.board.counts()["TODO"] == 0


def test_slugify_still_safe():
    assert slugify("CON") == "plan-con"
    assert slugify("  ") == "plan"
    assert slugify("a..b") == "a..b"
