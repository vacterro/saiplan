"""Persistence: atomic write, external-edit guard, backup rotation, recovery.

Failure-oriented (spec 9, 19): corrupt primary, corrupt temp, healthy backup
recovery, empty never replaces healthy backup, mirror failure isolation.
"""

from pathlib import Path

import pytest
from conftest import build_board

from saiplan.core.board import render_board
from saiplan.core.persistence import (
    BoardStore,
    CorruptBoardError,
    ExternalEditError,
    atomic_write,
    file_fingerprint,
    validate_snapshot,
)


@pytest.fixture
def store(tmp_path):
    bp = tmp_path / "board" / "BOARD.md"
    return BoardStore(bp, tmp_path / "board" / ".history")


def _write_healthy_board(path: Path):
    board = build_board("TODO S-001 First", "DOING S-002 Second")
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write(path, render_board(board))
    return board


def test_atomic_write_creates_file():
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        target = Path(d) / "BOARD.md"
        atomic_write(target, "## TODO\n")
        assert target.read_text(encoding="utf-8") == "## TODO\n"


def test_atomic_write_leaves_no_temp_litter(tmp_path):
    target = tmp_path / "f.txt"
    atomic_write(target, "data")
    leftovers = [f for f in tmp_path.iterdir() if "tmp-" in f.name]
    assert not leftovers


def test_atomic_write_into_missing_parent_creates_it(tmp_path):
    target = tmp_path / "a" / "b" / "c.md"
    atomic_write(target, "x")
    assert target.read_text(encoding="utf-8") == "x"


def test_atomic_write_to_nonwritable_target_fails(tmp_path):
    blocker = tmp_path / "blocker"
    blocker.write_text("i am a file, not a directory", encoding="utf-8")
    with pytest.raises(OSError):
        atomic_write(blocker / "f.txt", "x")


def test_load_and_save_roundtrip(store):
    text = render_board(build_board("TODO S-001 First"))
    store.save(text)
    assert store.load() == text
    assert not store.has_external_change()


def test_external_edit_detected_and_refuses_silent_save(store):
    store.save(render_board(build_board("TODO S-001 First")))
    # someone edits the file behind our back
    atomic_write(store.board_path, render_board(build_board("TODO S-999 Sneaky")))
    assert store.has_external_change()
    with pytest.raises(ExternalEditError):
        store.save(render_board(build_board("TODO S-002 Mine")))
    # file untouched by the refused save
    assert "S-999" in store.board_path.read_text(encoding="utf-8")


def test_save_with_allow_external_overwrites(store):
    store.save(render_board(build_board("TODO S-001 A")))
    atomic_write(store.board_path, render_board(build_board("TODO S-999 B")))
    store.save(render_board(build_board("TODO S-002 C")), allow_external=True)
    assert "S-002" in store.board_path.read_text(encoding="utf-8")


def test_missing_file_never_equals_empty_file(tmp_path):
    p = tmp_path / "b.md"
    assert file_fingerprint(p) == "MISSING"
    atomic_write(p, "")
    assert file_fingerprint(p) != "MISSING"


def test_save_writes_validated_snapshot(store):
    store.save(render_board(build_board("TODO S-001 A")))
    snaps = list(store.history_dir.glob("snapshot-*.board.md"))
    assert len(snaps) == 1
    assert validate_snapshot(snaps[0])
    assert "S-001" in snaps[0].read_text(encoding="utf-8")


def test_empty_or_corrupt_save_never_replaces_healthy_backup(store):
    # healthy board -> snapshot exists
    store.save(render_board(build_board("TODO S-001 A")))
    assert len(list(store.history_dir.glob("snapshot-*"))) == 1
    # an empty save must not rotate an empty snapshot over the healthy one
    store.save("")
    assert len(list(store.history_dir.glob("snapshot-*"))) == 1
    healthy = store.latest_snapshot().read_text(encoding="utf-8")
    assert "S-001" in healthy
    # a corrupt save must not either
    store.save("### GARBAGE not a board")
    assert len(list(store.history_dir.glob("snapshot-*"))) == 1
    assert store.latest_snapshot().read_text(encoding="utf-8") == healthy
    # next healthy save rotates normally
    store.save(render_board(build_board("TODO S-002 B")))
    assert len(list(store.history_dir.glob("snapshot-*"))) == 2


def test_snapshot_retention_prunes(store):
    store.snapshot_keep = 3
    for i in range(7):
        store.save(render_board(build_board(f"TODO S-{i:03d} T{i}")))
    snaps = sorted(store.history_dir.glob("snapshot-*.board.md"))
    assert len(snaps) == 3


def test_recover_from_corrupt_primary(store):
    store.save(render_board(build_board("TODO S-001 Golden")))
    atomic_write(store.board_path, "### GARBAGE!!! not a board")
    recovered = store.recover()
    assert "S-001" in recovered


def test_recover_skips_corrupt_snapshot(tmp_path):
    bp = tmp_path / "BOARD.md"
    st = BoardStore(bp, tmp_path / ".history")
    st.save(render_board(build_board("TODO S-001 Good")))
    st.save(render_board(build_board("TODO S-002 Also good")))
    # corrupt the newest snapshot, keep the older healthy one
    snaps = sorted(st.history_dir.glob("snapshot-*"))
    atomic_write(snaps[-1], "corrupt garbage")
    atomic_write(bp, "corrupt garbage too")
    recovered = st.recover()
    assert "S-001" in recovered


def test_recover_raises_when_no_valid_backup(tmp_path):
    bp = tmp_path / "BOARD.md"
    st = BoardStore(bp, tmp_path / ".history")
    st.save(render_board(build_board("TODO S-001 A")))
    for s in st.history_dir.glob("snapshot-*"):
        atomic_write(s, "garbage")
    atomic_write(bp, "garbage")
    with pytest.raises(CorruptBoardError):
        st.recover()


def test_mirror_written_and_isolated(tmp_path):
    bp = tmp_path / "BOARD.md"
    mirror = tmp_path / "mirror"
    st = BoardStore(bp, tmp_path / ".history", mirror_dir=mirror, mirror=True)
    st.save(render_board(build_board("TODO S-001 A")))
    assert (mirror / "BOARD.md").exists()
    assert "S-001" in (mirror / "BOARD.md").read_text(encoding="utf-8")


def test_mirror_failure_does_not_fail_save(tmp_path):
    bp = tmp_path / "BOARD.md"
    mirror = tmp_path / "mirror"
    st = BoardStore(bp, tmp_path / ".history", mirror_dir=mirror, mirror=True)
    # block mirror by making it a file
    mirror.write_text("not a dir", encoding="utf-8")
    st.save(render_board(build_board("TODO S-001 A")))  # must not raise
    assert "S-001" in bp.read_text(encoding="utf-8")


def test_mirror_never_read_back(tmp_path):
    bp = tmp_path / "BOARD.md"
    mirror = tmp_path / "mirror"
    st = BoardStore(bp, tmp_path / ".history", mirror_dir=mirror, mirror=True)
    st.save(render_board(build_board("TODO S-001 A")))
    # corrupt the mirror; the canonical state must stay untouched
    (mirror / "BOARD.md").write_text("MIRROR IS A LIE", encoding="utf-8")
    assert "S-001" in st.load()
