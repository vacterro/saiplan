"""Persistence: atomic write, strict save contract, external-edit guard,
backup rotation, recovery with corrupt-primary preservation.

Failure-oriented (spec 9, 19): a save is accepted ONLY for a strictly valid
BOARD; empty/corrupt/partial text is rejected before any write; a corrupt
primary is preserved byte-for-byte before recovery; the mirror never fails a
save and is never read back.
"""

import tempfile
from pathlib import Path

import pytest
from conftest import build_board

from saiplan.core.board import render_board
from saiplan.core.persistence import (
    BoardStore,
    BoardValidationError,
    CorruptBoardError,
    ExternalEditError,
    atomic_write,
    file_fingerprint,
    validate_snapshot,
)

PARTIAL_BOARD = (
    "## DOING\n## TODO\nHUMAN NOTE MUST SURVIVE\n- [ ] S-001 Good | malformed fragment\n"
    "- [ ] S-002 Also good\n## DONE\n## BLOCKED\n"
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


def test_empty_save_rejected(store):
    with pytest.raises(BoardValidationError):
        store.save("")


def test_corrupt_save_rejected(store):
    with pytest.raises(BoardValidationError):
        store.save("### GARBAGE not a board")


def test_partial_board_with_human_note_rejected(store):
    """A board with a malformed line / malformed field fragment must never be
    silently canonicalized — the human bytes would be destroyed (I3/I4/I5)."""
    with pytest.raises(BoardValidationError):
        store.save(PARTIAL_BOARD)
    # and the canonical file was never touched
    assert not store.board_path.exists()


def test_healthy_primary_untouched_by_rejected_saves(store):
    healthy = render_board(build_board("TODO S-001 A", "TODO S-002 B"))
    store.save(healthy)
    for bad in ("", "garbage", PARTIAL_BOARD):
        with pytest.raises(BoardValidationError):
            store.save(bad)
    assert store.board_path.read_text(encoding="utf-8") == healthy
    assert not store.has_external_change()


def test_unknown_wellformed_field_survives(store):
    """An unknown but well-formed field is a warning, preserved exactly."""
    text = (
        "## TODO\n- [ ] S-001 Buy SSD | alien-field: keepme | due: 2026-08-20\n"
        "## DOING\n## DONE\n## BLOCKED\n"
    )
    store.save(text)
    stored = store.board_path.read_text(encoding="utf-8")
    assert "alien-field: keepme" in stored


def test_external_edit_detected_and_refuses_silent_save(store):
    store.save(render_board(build_board("TODO S-001 First")))
    atomic_write(store.board_path, render_board(build_board("TODO S-999 Sneaky")))
    assert store.has_external_change()
    with pytest.raises(ExternalEditError):
        store.save(render_board(build_board("TODO S-002 Mine")))
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


def test_recover_and_adopt_preserves_corrupt_primary(store):
    store.save(render_board(build_board("TODO S-001 Golden")))
    atomic_write(store.board_path, "### CORRUPT RAW BYTES KEEP ME")
    text = store.recover_and_adopt()
    assert "S-001" in text
    # the corrupt primary was preserved byte-for-byte before recovery
    preserved = list(store.history_dir.glob("corrupt-*.board.md"))
    assert len(preserved) == 1
    assert "CORRUPT RAW BYTES KEEP ME" in preserved[0].read_text(encoding="utf-8")
    # disk / loaded_text / guard now agree on the restored state
    assert store.loaded_text == text
    assert not store.has_external_change()


def test_recover_and_adopt_missing_board_with_snapshot(store):
    """BOARD.md missing but a snapshot exists -> restored + adopted."""
    store.save(render_board(build_board("TODO S-001 Golden")))
    store.board_path.unlink()
    text = store.recover_and_adopt()
    assert "S-001" in text
    assert store.board_path.exists()
    assert not store.has_external_change()


def test_recover_and_adopt_without_snapshot_refuses(store):
    """Missing/corrupt BOARD, no snapshot -> CorruptBoardError, primary
    untouched, no partial board adopted."""
    store.save(render_board(build_board("TODO S-001 A")))
    for s in store.history_dir.glob("snapshot-*"):
        atomic_write(s, "garbage")
    atomic_write(store.board_path, "garbage primary")
    with pytest.raises(CorruptBoardError):
        store.recover_and_adopt()
    assert "garbage primary" in store.board_path.read_text(encoding="utf-8")


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
    mirror.write_text("not a dir", encoding="utf-8")
    st.save(render_board(build_board("TODO S-001 A")))
    assert "S-001" in bp.read_text(encoding="utf-8")


def test_mirror_never_read_back(tmp_path):
    bp = tmp_path / "BOARD.md"
    mirror = tmp_path / "mirror"
    st = BoardStore(bp, tmp_path / ".history", mirror_dir=mirror, mirror=True)
    st.save(render_board(build_board("TODO S-001 A")))
    (mirror / "BOARD.md").write_text("MIRROR IS A LIE", encoding="utf-8")
    assert "S-001" in st.load()
