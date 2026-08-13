"""App config: exe-adjacent `data/config.json`, defaults + merge, atomic write.

Pattern: SAIPENVIEW config (audited). Unknown/corrupt config falls back to
defaults; unknown keys are ignored; write is temp + replace.

Every key is VALIDATED and coerced on load: a wrong-typed value (scale:
"banana", snapshot_keep: "many") falls back to that key's default. One broken
setting must never brick startup (I8).
"""

from __future__ import annotations

import json
import math
import threading
from pathlib import Path

from .persistence import atomic_write

_SCALE_MIN, _SCALE_MAX = 0.5, 2.0
_SNAPSHOT_KEEP_MIN, _SNAPSHOT_KEEP_MAX = 1, 200


def _as_str(value, default):
    return value if isinstance(value, str) else default


def _as_bool(value, default):
    return value if isinstance(value, bool) else default


def _as_float_range(value, default, lo, hi):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return default
    value = float(value)
    if not math.isfinite(value) or not (lo <= value <= hi):
        return default
    return value


def _as_int_range(value, default, lo, hi):
    if isinstance(value, bool) or not isinstance(value, int):
        return default
    if not (lo <= value <= hi):
        return default
    return value


def _as_str_list(value, default):
    if isinstance(value, list) and all(isinstance(v, str) for v in value):
        return value
    return default


def _as_str_dict(value, default):
    if isinstance(value, dict) and all(isinstance(k, str) for k in value):
        return value
    return default


_VALIDATORS = {
    "theme": lambda v: _as_str(v, "goldenvintage"),
    "scale": lambda v: _as_float_range(v, 1.0, _SCALE_MIN, _SCALE_MAX),
    "single_focus": lambda v: _as_bool(v, True),
    "snapshot_keep": lambda v: _as_int_range(v, 14, _SNAPSHOT_KEEP_MIN, _SNAPSHOT_KEEP_MAX),
    "mirror_enabled": lambda v: _as_bool(v, False),
    "mirror_dir": lambda v: _as_str(v, ""),
    "language": lambda v: _as_str(v, "en"),
    "always_on_top": lambda v: _as_bool(v, False),
    "sound_events": lambda v: _as_str_dict(v, {}),
    "sound_volume": lambda v: _as_int_range(v, 5, 0, 10),
    "sound_enabled": lambda v: _as_bool(v, True),
    "window_geometry": lambda v: _as_str(v, ""),
    "recent_plans": lambda v: _as_str_list(v, []),
    "pinned_plans": lambda v: _as_str_list(v, []),
}


def _validated_defaults() -> dict:
    return {k: _VALIDATORS[k](v) for k, v in _RAW_DEFAULTS.items()}


_RAW_DEFAULTS = {
    "theme": "goldenvintage",  # I11: Golden Vintage is default
    "scale": 1.0,
    "single_focus": True,
    "snapshot_keep": 14,
    "mirror_enabled": False,
    "mirror_dir": "",
    "language": "en",
    "always_on_top": False,
    "sound_events": {},
    "sound_volume": 5,
    "sound_enabled": True,
    "window_geometry": "",
    "recent_plans": [],
    "pinned_plans": [],
}

DEFAULTS = _validated_defaults()

_lock = threading.Lock()


class Config:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.data = dict(DEFAULTS)

    def load(self) -> None:
        try:
            stored = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError, TypeError, UnicodeDecodeError):
            return
        if not isinstance(stored, dict):
            return
        # per-key validation: a broken value falls back to that key's default
        for key, validator in _VALIDATORS.items():
            if key in stored:
                self.data[key] = validator(stored[key])

    def save(self) -> None:
        with _lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            merged = dict(DEFAULTS)
            merged.update({k: v for k, v in self.data.items() if k in DEFAULTS})
            atomic_write(self.path, json.dumps(merged, indent=2))

    def get(self, key, default=None):
        return self.data.get(key, default)

    def set(self, key, value):
        self.data[key] = value
