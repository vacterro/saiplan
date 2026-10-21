"""Sounds (spec 12/19): dynamic enumeration, event mapping, stale-name heal,
missing file safety, personal pack precedence."""

from pathlib import Path

import pytest

from saiplan.extras.sounds import (
    DEFAULT_EVENTS,
    KNOWN_EVENTS,
    SoundLibrary,
    SoundPlayer,
    SoundRegistry,
)

SOUNDS_DIR = Path(__file__).resolve().parents[1] / "sounds"
MANIFEST = Path(__file__).resolve().parents[1] / "sounds-redistributable.manifest"


def _manifest_names() -> set[str]:
    return {
        line.strip().replace("\\", "/")
        for line in MANIFEST.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    }


def test_library_enumerates_dynamically():
    lib = SoundLibrary(SOUNDS_DIR)
    files = lib.all_files()
    assert len(files) == len(_manifest_names())
    assert all(f.endswith(".wav") for f in files)
    assert files == sorted(files)


def test_shipped_sounds_match_the_redistributable_manifest():
    """Only allowlisted, synthesized sounds may ship in the repository."""
    lib = SoundLibrary(SOUNDS_DIR)
    shipped = set(lib.all_files())
    assert shipped == _manifest_names()


def test_library_no_hardcoded_count(tmp_path):
    lib = SoundLibrary(tmp_path)
    assert lib.count() == 0
    (tmp_path / "a.wav").write_bytes(b"x")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "b.wav").write_bytes(b"x")
    assert lib.count() == 2
    assert lib.path_for("sub/b.wav") is not None


def test_nested_path_resolution_platform_neutral(tmp_path):
    """Nested paths resolve via pathlib parts on ANY OS (audit failure:
    rel.replace('/', '\\\\') was Windows-only)."""
    lib = SoundLibrary(tmp_path)
    (tmp_path / "cs_style").mkdir()
    (tmp_path / "cs_style" / "buttonclick.wav").write_bytes(b"RIFF")
    assert lib.path_for("cs_style/buttonclick.wav") is not None
    assert lib.path_for("cs_style/buttonclick.wav").is_file()


def test_path_traversal_rejected(tmp_path):
    outside = tmp_path.parent / "outside.wav"
    outside.write_bytes(b"RIFF")
    lib = SoundLibrary(tmp_path)
    assert lib.path_for("../outside.wav") is None
    assert lib.path_for("a/../../outside.wav") is None
    assert lib.path_for("..") is None


def test_missing_file_returns_none(tmp_path):
    lib = SoundLibrary(tmp_path)
    assert lib.path_for("nope.wav") is None
    assert lib.path_for("") is None
    assert lib.path_for("sub/nope.wav") is None


def test_missing_sound_dir_is_empty_not_crash():
    lib = SoundLibrary(Path("V:/does/not/exist/sounds"))
    assert lib.count() == 0
    assert lib.all_files() == []
    assert lib.path_for("x.wav") is None


def test_every_default_event_file_exists():
    lib = SoundLibrary(SOUNDS_DIR)
    available = set(lib.all_files())
    for event, file in DEFAULT_EVENTS.items():
        assert file in available, f"{event} default {file} missing"
    assert set(DEFAULT_EVENTS) == set(KNOWN_EVENTS)


def test_registry_normalizes_stale_names(tmp_path):
    (tmp_path / "ok.wav").write_bytes(b"RIFF")
    lib = SoundLibrary(tmp_path)
    reg = SoundRegistry(
        lib, {"timer_finished": {"file": "ghost.wav", "enabled": True, "volume": 1.0}}
    )
    # ghost.wav is not in the library -> heals to the default, which is also
    # absent here -> empty file, disabled effectively, no crash
    assert reg.events["timer_finished"]["file"] == ""
    assert reg.file_for("timer_finished") is None


def test_registry_defaults_on_missing_entry(tmp_path):
    (tmp_path / "timer_finished.wav").write_bytes(b"RIFF")
    lib = SoundLibrary(tmp_path)
    reg = SoundRegistry(lib, None)
    assert reg.file_for("timer_finished") == tmp_path / "timer_finished.wav"


@pytest.mark.parametrize(
    "entry",
    [
        {"file": [], "enabled": True, "volume": 1.0},
        {"file": None, "enabled": "yes", "volume": "banana"},
        {"file": "x.wav", "enabled": 1, "volume": float("nan")},
        {"file": "x.wav", "enabled": False, "volume": 99},
    ],
)
def test_registry_malformed_payloads_use_safe_values(tmp_path, entry):
    (tmp_path / "x.wav").write_bytes(b"RIFF")
    reg = SoundRegistry(SoundLibrary(tmp_path), {"timer_finished": entry})
    normalized = reg.events["timer_finished"]
    assert isinstance(normalized["file"], str)
    assert isinstance(normalized["enabled"], bool)
    assert 0.0 <= normalized["volume"] <= 1.0


def test_registry_events_reasonable_defaults():
    lib = SoundLibrary(SOUNDS_DIR)
    reg = SoundRegistry(lib)
    for event in KNOWN_EVENTS:
        entry = reg.events[event]
        assert entry["enabled"] is True
        assert 0.0 <= entry["volume"] <= 1.0


def test_registry_to_config_roundtrip(tmp_path):
    (tmp_path / "a.wav").write_bytes(b"RIFF")
    lib = SoundLibrary(tmp_path)
    reg = SoundRegistry(lib)
    cfg = reg.to_config()
    reg2 = SoundRegistry(lib, cfg)
    assert reg2.to_config() == cfg


def test_player_never_crashes_on_missing_or_corrupt(tmp_path):
    player = SoundPlayer()
    player.play_file(Path("V:/nope/missing.wav"), 1.0)  # must not raise
    (tmp_path / "junk.wav").write_bytes(b"this is not a wav")
    player.play_file(tmp_path / "junk.wav", 0.5)  # must not raise
    player.stop_preview()  # no-op when idle


def test_player_volume_clamped(tmp_path):
    (tmp_path / "a.wav").write_bytes(b"RIFFx")
    player = SoundPlayer()
    player.play_file(tmp_path / "a.wav", 3.0)  # clamped, no crash
    player.play_file(tmp_path / "a.wav", -1.0)  # clamped, no crash


# ---------------------------------------------------------------------------
# Personal sound pack: precedence, isolation, missing-folder safety
# ---------------------------------------------------------------------------


def test_personal_pack_wins_over_shipped_file(tmp_path):
    shipped = tmp_path / "shipped"
    personal = tmp_path / "personal"
    shipped.mkdir()
    personal.mkdir()
    (shipped / "click.wav").write_bytes(b"RIFF-shipped")
    (personal / "click.wav").write_bytes(b"RIFF-personal")

    lib = SoundLibrary(shipped, personal)
    assert lib.all_files() == ["click.wav"]
    assert lib.path_for("click.wav").read_bytes() == b"RIFF-personal"


def test_personal_pack_adds_files_without_copying_them(tmp_path):
    shipped = tmp_path / "shipped"
    personal = tmp_path / "personal"
    shipped.mkdir()
    personal.mkdir()
    (shipped / "click.wav").write_bytes(b"RIFF")
    (personal / "GENIE.wav").write_bytes(b"RIFF-personal")

    lib = SoundLibrary(shipped, personal)
    assert set(lib.all_files()) == {"click.wav", "GENIE.wav"}
    # The personal file is read in place, never duplicated into the shipped root.
    assert sorted(p.name for p in shipped.iterdir()) == ["click.wav"]
    assert lib.path_for("GENIE.wav") == (personal / "GENIE.wav").resolve()


def test_personal_pack_can_provide_every_sound(tmp_path):
    """A public build with no personal pack still ships a complete palette."""
    personal = tmp_path / "empty"
    personal.mkdir()
    lib = SoundLibrary(SOUNDS_DIR, personal)
    assert set(lib.all_files()) == _manifest_names()


def test_missing_personal_pack_is_not_an_error(tmp_path):
    lib = SoundLibrary(SOUNDS_DIR, tmp_path / "does-not-exist")
    assert lib.count() == len(_manifest_names())
    (tmp_path / "gone.wav").write_bytes(b"RIFF")
    lib = SoundLibrary(SOUNDS_DIR, tmp_path / "gone.wav")  # a FILE, not a dir
    assert lib.count() == len(_manifest_names())


def test_personal_pack_traversal_does_not_escape(tmp_path):
    shipped = tmp_path / "shipped"
    personal = tmp_path / "personal"
    shipped.mkdir()
    personal.mkdir()
    (tmp_path / "outside.wav").write_bytes(b"RIFF")
    lib = SoundLibrary(shipped, personal)
    assert lib.path_for("../outside.wav") is None
    assert lib.path_for("../../outside.wav") is None


def test_private_folders_stay_out_of_the_picker(tmp_path):
    shipped = tmp_path / "shipped"
    personal = tmp_path / "personal"
    shipped.mkdir()
    personal.mkdir()
    (personal / "public.wav").write_bytes(b"RIFF")
    (personal / "_scratch").mkdir()
    (personal / "_scratch" / "hidden.wav").write_bytes(b"RIFF")
    lib = SoundLibrary(shipped, personal)
    assert lib.all_files() == ["public.wav"]


def test_switching_packs_keeps_the_saved_choice(tmp_path):
    shipped = tmp_path / "shipped"
    pack_a = tmp_path / "a"
    pack_b = tmp_path / "b"
    for directory in (shipped, pack_a, pack_b):
        directory.mkdir()
    (shipped / "click.wav").write_bytes(b"RIFF")
    (pack_a / "my_click.wav").write_bytes(b"RIFF")
    (pack_b / "my_click.wav").write_bytes(b"RIFF")

    reg_a = SoundRegistry(SoundLibrary(shipped, pack_a))
    reg_a.set("click", "my_click.wav")
    saved = reg_a.to_config()

    # Pack gone for a session: the event falls back but the choice is retained.
    reg_missing = SoundRegistry(SoundLibrary(shipped, tmp_path / "gone"), saved)
    assert reg_missing.events["click"]["file"] == "click.wav"
    assert reg_missing.events["click"]["requested"] == ""

    reg_b = SoundRegistry(SoundLibrary(shipped, pack_b), saved)
    assert reg_b.events["click"]["file"] == "my_click.wav"
    assert reg_b.events["click"]["enabled"] is True
    assert reg_b.to_config()["click"]["volume"] == saved["click"]["volume"]


def test_legacy_config_without_pack_dir_loads(tmp_path):
    reg = SoundRegistry(SoundLibrary(SOUNDS_DIR), {"click": {"file": "click.wav"}})
    assert reg.events["click"]["file"] == "click.wav"
    assert reg.events["click"]["volume"] == 1.0


def test_unknown_legacy_sound_heals_to_default_without_crash(tmp_path):
    reg = SoundRegistry(SoundLibrary(SOUNDS_DIR), {"click": {"file": "GENIE.wav"}})
    assert reg.events["click"]["file"] == "click.wav"
    assert reg.file_for("click") is not None
