"""App config: exe-adjacent `data/config.json`, defaults + merge, atomic write.

Pattern: SAIPENVIEW config (audited). Unknown/corrupt config falls back to
defaults; unknown keys are ignored; write is temp + replace.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path

from .persistence import atomic_write

DEFAULTS = {
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

_lock = threading.Lock()


class Config:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.data = dict(DEFAULTS)

    def load(self) -> None:
        try:
            stored = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError, TypeError):
            return
        if isinstance(stored, dict):
            self.data.update({k: v for k, v in stored.items() if k in DEFAULTS})

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
