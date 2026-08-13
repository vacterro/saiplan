"""Global hotkeys via RegisterHotKey (ctypes), layout-aware.

Pattern from the audited FastPrompter: `VkKeyScanW` maps a char to its
virtual-key code + shift state for the ACTIVE keyboard layout, so a shortcut
written as a symbol (`?`, `+`, `!`) resolves to the base key + MOD_SHIFT on
any layout. In-app shortcuts go through Qt; this is only for global hotkeys.
"""

from __future__ import annotations

import ctypes
import sys

if sys.platform == "win32":
    user32 = ctypes.windll.user32
else:
    user32 = None

MOD_ALT = 0x1
MOD_CONTROL = 0x2
MOD_SHIFT = 0x4
MOD_WIN = 0x8

VK_SHIFT = 0x10
VK_CONTROL = 0x11
VK_MENU = 0x12


def vk_scan(char: str):
    """-> (vk, modifiers). Resolves a single char against the active layout."""
    if user32 is None:
        return None, 0
    vk = user32.VkKeyScanW(ord(char))
    if vk == -1:
        return None, 0
    code = vk & 0xFF
    state = (vk >> 8) & 0xFF
    mods = 0
    if state & 1:
        mods |= MOD_SHIFT
    if state & 2:
        mods |= MOD_CONTROL
    if state & 4:
        mods |= MOD_ALT
    return code, mods


def parse_hotkey(spec: str):
    """Parse `Ctrl+Shift+K` or `Alt+?` into (modifiers, vk).

    Modifiers: Ctrl, Alt, Shift, Win (case-insensitive, any order).
    Key semantics:
    - a single ASCII letter -> its FIXED virtual key (0x41..0x5A). Letters are
      layout-independent: VkKeyScanW returns -1 for Latin letters on non-Latin
      layouts, and a hotkey must mean the same key everywhere.
    - any other single char (symbols like `?`, `+`, `!`) -> VkKeyScanW against
      the ACTIVE layout, so a symbol shortkey resolves on any keyboard; the
      implied Shift for shifted symbols is folded into `mods`.
    - named keys: F1..F12, Space, Enter, Esc, Tab, Del, Ins.
    """
    mods = 0
    named = {
        "f1": 0x70,
        "f2": 0x71,
        "f3": 0x72,
        "f4": 0x73,
        "f5": 0x74,
        "f6": 0x75,
        "f7": 0x76,
        "f8": 0x77,
        "f9": 0x78,
        "f10": 0x79,
        "f11": 0x7A,
        "f12": 0x7B,
        "space": 0x20,
        "enter": 0x0D,
        "esc": 0x1B,
        "tab": 0x09,
        "del": 0x2E,
        "ins": 0x2D,
    }
    parts = [p.strip() for p in spec.split("+")]
    key = parts[-1].lower()
    for mod in parts[:-1]:
        m = mod.lower()
        if m in ("ctrl", "control", "ctl"):
            mods |= MOD_CONTROL
        elif m in ("alt",):
            mods |= MOD_ALT
        elif m in ("shift",):
            mods |= MOD_SHIFT
        elif m in ("win", "windows", "super"):
            mods |= MOD_WIN
        else:
            raise ValueError(f"unknown modifier {mod!r}")
    if len(key) == 1:
        if "a" <= key <= "z":
            vk = ord(key.upper()) - ord("A") + 0x41
        else:
            vk, key_mods = vk_scan(key)
            if vk is None:
                raise ValueError(f"cannot resolve key {key!r} on this layout")
            mods |= key_mods
    elif key in named:
        vk = named[key]
    else:
        raise ValueError(f"unknown key {key!r}")
    return mods, vk


class Hotkey:
    def __init__(self, spec: str, callback, id_: int):
        self.spec = spec
        self.callback = callback
        self.id = id_
        self.mods, self.vk = parse_hotkey(spec)


class HotkeyRegistrar:
    """Register/unregister global hotkeys against a window handle."""

    def __init__(self, hwnd=None):
        self._hwnd = hwnd or 0
        self._hotkeys: dict[int, Hotkey] = {}
        self._next_id = 1

    def register(self, spec: str, callback) -> Hotkey | None:
        if user32 is None:
            return None
        hotkey = Hotkey(spec, callback, self._next_id)
        self._next_id += 1
        ok = user32.RegisterHotKey(self._hwnd, hotkey.id, hotkey.mods, hotkey.vk)
        if not ok:
            return None
        self._hotkeys[hotkey.id] = hotkey
        return hotkey

    def unregister(self, hotkey: Hotkey) -> None:
        user32.UnregisterHotKey(self._hwnd, hotkey.id)
        self._hotkeys.pop(hotkey.id, None)

    def dispatch(self, id_: int) -> bool:
        hotkey = self._hotkeys.get(id_)
        if hotkey is None:
            return False
        hotkey.callback()
        return True
