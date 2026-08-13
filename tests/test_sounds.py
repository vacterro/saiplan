"""Sounds (spec 12/19): dynamic enumeration, event mapping, stale-name heal,
missing file safety."""

from pathlib import Path

from saiplan.extras.sounds import (
    DEFAULT_EVENTS,
    KNOWN_EVENTS,
    SoundLibrary,
    SoundPlayer,
    SoundRegistry,
)

SOUNDS_DIR = Path(__file__).resolve().parents[1] / "sounds"


def test_library_enumerates_dynamically():
    lib = SoundLibrary(SOUNDS_DIR)
    files = lib.all_files()
    assert len(files) == 414
    assert all(f.endswith(".wav") for f in files)
    assert all("/" not in f or f.startswith("cs_style/") for f in files)


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
    (tmp_path / "chime_bell_ding1.wav").write_bytes(b"RIFF")
    lib = SoundLibrary(tmp_path)
    reg = SoundRegistry(lib, None)
    assert reg.file_for("timer_finished") == tmp_path / "chime_bell_ding1.wav"


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
