"""Plan directory lifecycle + portable path safety."""

import pytest

from saiplan.core.plan import PlanStore, slugify


@pytest.fixture
def store(tmp_path):
    return PlanStore(tmp_path / "plans")


def test_create_plan_writes_plan_and_board(store, tmp_path):
    plan = store.create("My Great Plan", "Ship it")
    assert plan.directory.exists()
    assert plan.plan_md_path.exists()
    assert plan.board_path.read_text(encoding="utf-8").startswith("## DOING")
    assert plan.name == "My Great Plan"
    assert plan.objective == "Ship it"


def test_list_and_get_plans(store):
    store.create("Alpha")
    store.create("Beta", "obj")
    plans = store.list_plans()
    assert {p.name for p in plans} == {"Alpha", "Beta"}
    got = store.get(plans[0].plan_id)
    assert got.name == plans[0].name


def test_slugify_safety():
    assert slugify("Buy new SSD") == "buy-new-ssd"
    assert slugify("  ") == "plan"
    assert slugify("Русский план") == "plan"  # non-ascii stripped
    assert slugify("CON") == "plan-con"  # windows device name
    assert slugify("a..b") == "a..b"  # interior dots are safe
    assert slugify("name.") == "name"  # trailing dot stripped


def test_same_name_creates_distinct_plan_ids(store):
    a = store.create("Same Name")
    b = store.create("Same Name")
    assert a.plan_id != b.plan_id
    assert a.directory != b.directory
    assert a.directory.exists() and b.directory.exists()


def test_foreign_plan_md_is_tolerant(store):
    plan = store.create("Tolerant")
    plan.plan_md_path.write_text("# Tolerant\n\n## Objective\nWhatever\n", encoding="utf-8")
    got = store.get(plan.plan_id)
    assert got.objective == "Whatever"


def test_board_paths_all_under_plan_dir(store):
    plan = store.create("Paths")
    for p in (
        plan.board_path,
        plan.log_path,
        plan.plan_md_path,
        plan.timelog_path,
        plan.notes_dir,
        plan.history_dir,
        plan.trash_path,
    ):
        assert str(p).startswith(str(plan.directory))
