"""Portable paths, single instance, hotkeys, crash logging (spec 10/19)."""

import os
import sys
from pathlib import Path

import pytest

from saiplan.platform import paths
from saiplan.platform.hotkeys import MOD_ALT, MOD_CONTROL, MOD_SHIFT, parse_hotkey, vk_scan
from saiplan.platform.single_instance import SingleInstanceMutex, new_token


def test_layout_under_given_root():
    layout = paths.resolve_layout(Path("X:/somewhere/SAIPLAN"))
    assert layout["root"] == Path("X:/somewhere/SAIPLAN")
    assert layout["data"] == Path("X:/somewhere/SAIPLAN/data")
    assert layout["plans"] == Path("X:/somewhere/SAIPLAN/data/plans")
    assert layout["config"] == Path("X:/somewhere/SAIPLAN/data/config.json")
    assert layout["themes"] == Path("X:/somewhere/SAIPLAN/themes")
    assert layout["sounds"] == Path("X:/somewhere/SAIPLAN/sounds")
    assert layout["logs"] == Path("X:/somewhere/SAIPLAN/logs")


def test_layout_follows_folder_move(tmp_path):
    """Portable (I14): recompute layout from a moved root, no absolute junk."""
    root = tmp_path / "SAIPLAN"
    (root / "data").mkdir(parents=True)
    layout = paths.resolve_layout(root)
    assert layout["plans"].parent == root / "data"
    # move the whole folder
    moved = tmp_path / "moved-here"
    (root / "data" / "plans").mkdir()
    os.replace(root, moved)
    layout2 = paths.resolve_layout(moved)
    assert layout2["plans"] == moved / "data" / "plans"
    assert layout2["plans"].exists()


def test_layout_status_with_unicode_and_spaces(tmp_path):
    root = tmp_path / "Мой план folder"
    layout = paths.resolve_layout(root)
    ok, _msg = paths.layout_status(layout)
    assert ok
    paths.ensure_layout_dirs(layout)
    assert layout["plans"].exists()
    assert layout["logs"].exists()


def test_layout_status_readonly_root_fails_loudly(tmp_path):
    root = tmp_path / "SAIPLAN"
    root.mkdir()
    (root / "data").write_text("i am a file", encoding="utf-8")
    ok, msg = paths.layout_status(paths.resolve_layout(root))
    assert not ok
    assert "data" in msg


def test_dir_writable(tmp_path):
    assert paths.dir_writable(tmp_path) is True
    blocker = tmp_path / "file"
    blocker.write_text("x", encoding="utf-8")
    assert paths.dir_writable(blocker) is False


def test_mutex_first_and_second(tmp_path):
    name = "SaiplanTest"
    with SingleInstanceMutex(name) as first:
        assert first.is_first
        with SingleInstanceMutex(name) as second:
            assert not second.is_first
        with SingleInstanceMutex(name) as third:
            assert not third.is_first
    # released -> a fresh process would be first again
    with SingleInstanceMutex(name) as after:
        assert after.is_first


def test_token_is_random():
    assert new_token() != new_token()


def test_vk_scan_shape():
    # layout-aware scan: returns (vk, mods); vk may be None on layouts that
    # cannot type the char. Assert the contract, not a specific layout.
    result = vk_scan("a")
    assert isinstance(result, tuple) and len(result) == 2
    vk, mods = vk_scan("?")
    assert vk is None or (isinstance(vk, int) and isinstance(mods, int))


def test_parse_hotkey_specs():
    # letters are layout-independent: fixed VK regardless of active keyboard
    mods, vk = parse_hotkey("Ctrl+Shift+K")
    assert mods == MOD_CONTROL | MOD_SHIFT
    assert vk == 0x4B
    mods, vk = parse_hotkey("Ctrl+K")
    assert mods == MOD_CONTROL
    assert vk == 0x4B
    mods, vk = parse_hotkey("Alt+Space")
    assert mods == MOD_ALT
    assert vk == 0x20
    mods, vk = parse_hotkey("Ctrl+Alt+F12")
    assert mods == MOD_CONTROL | MOD_ALT
    assert vk == 0x7B


def test_parse_hotkey_bad_spec():
    with pytest.raises(ValueError):
        parse_hotkey("Foo+Bar")
    with pytest.raises(ValueError):
        parse_hotkey("Ctrl")


def test_crash_log_written(tmp_path):
    from saiplan.logging import setup_logging

    logger = setup_logging(tmp_path)
    assert (tmp_path / "saiplan.log").exists()
    # the excepthook writes a crash.log
    old_hook = sys.excepthook
    setup_logging(tmp_path)
    try:
        sys.excepthook(ValueError, ValueError("boom"), None)
    finally:
        sys.excepthook = old_hook
    # excepthook with None tb still logs
    logger.info("no crash here")
    assert (tmp_path / "crash.log").exists()
