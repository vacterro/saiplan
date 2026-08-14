"""Sounds (extras, spec 12). Sounds are ASSETS, never logic.

- Library: recursive .wav discovery under `sounds/`, enumerated dynamically
  (no hardcoded count), forward-slash relative names.
- Events: per-event `{file, enabled, volume}` mapping persisted in config.
- Player: QSoundEffect when available, else winsound; preview bypasses toggles;
  a missing/corrupt sound file never crashes the app (silent skip).
"""

from __future__ import annotations

import logging
import math
from pathlib import Path

logger = logging.getLogger("saiplan")

DEFAULT_EVENTS = {
    "timer_finished": "chime_bell_ding1.wav",
    "pomodoro_work_done": "success_levelup.wav",
    "break_finished": "whoosh_digital_small_whoosh.wav",
    "due_reminder": "notify_notification3.wav",
    "ticket_done": "success_vote_success.wav",
    "blocked_warning": "alert_warn01b.wav",
    "plan_completed": "coin_kaching.wav",
    "click": "Click.wav",
    "undo": "menu_launch_upmenu1.wav",
}

KNOWN_EVENTS = tuple(DEFAULT_EVENTS.keys())


class SoundLibrary:
    """Enumerate all shipped sound assets, dynamically."""

    def __init__(self, sounds_dir: Path):
        self.sounds_dir = Path(sounds_dir).resolve()

    def all_files(self) -> list[str]:
        """Relative forward-slash names, stable order."""
        if not self.sounds_dir.is_dir():
            return []
        out = []
        for path in sorted(self.sounds_dir.rglob("*.wav")):
            out.append(path.relative_to(self.sounds_dir).as_posix())
        return out

    def count(self) -> int:
        return len(self.all_files())

    def path_for(self, rel: str) -> Path | None:
        """Resolve a relative name to a real file (or None if missing).

        Platform-neutral via PurePosixPath parts; the result MUST stay inside
        the sounds dir — `../` escapes are rejected outright."""
        if not rel:
            return None
        try:
            from pathlib import PurePosixPath

            parts = PurePosixPath(rel).parts
            if not parts or ".." in parts:
                return None
            candidate = self.sounds_dir.joinpath(*parts).resolve()
        except (ValueError, OSError):
            return None
        if self.sounds_dir not in candidate.parents and candidate != self.sounds_dir:
            return None
        if candidate.is_file():
            return candidate
        return None


class SoundRegistry:
    """Per-event mapping, persisted through the app config dict.

    Stale names heal on load: if the mapped file no longer exists the event
    falls back to its default file, then to none — never to a crash.
    """

    def __init__(self, library: SoundLibrary, events: dict | None = None):
        self.library = library
        self._available = set(library.all_files())
        self.events: dict[str, dict] = {}
        for event in KNOWN_EVENTS:
            self.events[event] = self._normalize(events, event, DEFAULT_EVENTS[event])

    def _normalize(self, events, event: str, default: str) -> dict:
        default = default if default in self._available else ""
        if not isinstance(events, dict):
            return {"file": default, "enabled": True, "volume": 1.0}
        entry = events.get(event)
        if not isinstance(entry, dict):
            return {"file": default, "enabled": True, "volume": 1.0}
        requested = entry.get("file")
        file = requested if isinstance(requested, str) and requested in self._available else default
        enabled = entry.get("enabled", True)
        if not isinstance(enabled, bool):
            enabled = True
        volume = entry.get("volume", 1.0)
        if isinstance(volume, bool) or not isinstance(volume, (int, float)):
            volume = 1.0
        volume = float(volume)
        if not math.isfinite(volume):
            volume = 1.0
        return {
            "file": file,
            "enabled": enabled,
            "volume": max(0.0, min(1.0, volume)),
        }

    def to_config(self) -> dict:
        return {e: self.events[e] for e in KNOWN_EVENTS}

    def set(
        self, event: str, file: str, enabled: bool | None = None, volume: float | None = None
    ) -> None:
        if event not in self.events:
            return
        entry = self.events[event]
        if file in self._available:
            entry["file"] = file
        if enabled is not None:
            entry["enabled"] = enabled
        if volume is not None:
            entry["volume"] = max(0.0, min(1.0, float(volume)))

    def file_for(self, event: str) -> Path | None:
        entry = self.events.get(event)
        if not entry or not entry["enabled"]:
            return None
        return self.library.path_for(entry["file"])

    def volume_for(self, event: str) -> float:
        entry = self.events.get(event) or {}
        return float(entry.get("volume", 1.0))


class SoundPlayer:
    """Play a sound file without ever crashing. Qt parts imported lazily so
    headless tests can exercise the registry without a QApplication."""

    def __init__(self):
        self._effect = None
        self._uses_qt = False
        self._qt_available = False
        self._backend = self._pick_backend()

    def _pick_backend(self) -> str:
        try:
            from PyQt6.QtCore import QCoreApplication
            from PyQt6.QtMultimedia import QSoundEffect  # noqa: F401

            if QCoreApplication.instance() is not None:
                self._qt_available = True
                return "qt"
        except Exception as e:  # noqa: BLE001
            logger.debug("Qt sound backend unavailable: %s", e)
        try:
            import winsound  # noqa: F401

            return "winsound"
        except Exception:  # noqa: BLE001
            return "none"

    def play_file(self, path: Path, volume: float = 1.0) -> None:
        try:
            if self._backend == "qt":
                self._play_qt(path, volume)
            elif self._backend == "winsound":
                self._play_winsound(path, volume)
        except Exception:
            logger.warning("sound playback failed for %s", path, exc_info=True)

    def preview(self, path: Path, volume: float = 1.0) -> None:
        """Preview bypasses the enabled toggle but still never crashes."""
        self.play_file(path, volume)

    def stop_preview(self) -> None:
        if self._effect is not None:
            try:
                self._effect.stop()
            except Exception as e:  # noqa: BLE001
                logger.debug("stop_preview failed: %s", e)

    def _play_qt(self, path: Path, volume: float) -> None:
        from PyQt6.QtCore import QUrl
        from PyQt6.QtMultimedia import QSoundEffect

        if self._effect is None:
            self._effect = QSoundEffect()
        self._effect.setVolume(max(0.0, min(1.0, volume)))
        self._effect.setSource(QUrl.fromLocalFile(str(path)))
        self._effect.play()

    def _play_winsound(self, path: Path, volume: float) -> None:
        import winsound

        if volume < 0.95:
            # winsound has no volume: rescale the WAV samples
            data = self._rescale(path, volume)
            if data is not None:
                winsound.PlaySound(data, winsound.SND_MEMORY)
                return
        winsound.PlaySound(str(path), winsound.SND_FILENAME | winsound.SND_ASYNC)

    @staticmethod
    def _rescale(path: Path, volume: float) -> bytes | None:
        try:
            raw = path.read_bytes()
        except OSError:
            return None
        # find the 'data' chunk
        try:
            import struct

            offset = 12
            while offset + 8 <= len(raw):
                chunk_id = raw[offset : offset + 4]
                size = struct.unpack("<I", raw[offset + 4 : offset + 8])[0]
                if chunk_id == b"data":
                    data_start = offset + 8
                    data_end = min(len(raw), data_start + size)
                    samples = bytearray(raw[data_start:data_end])
                    bps = struct.unpack("<H", raw[34:36])[0]
                    if bps == 16:
                        for i in range(0, len(samples) - 1, 2):
                            s = struct.unpack("<h", samples[i : i + 2])[0]
                            samples[i : i + 2] = struct.pack("<h", int(s * volume))
                    return raw[:data_start] + bytes(samples)
                offset += 8 + size + (size & 1)
        except Exception:  # noqa: BLE001
            return None
        return None


class NullSoundRegistry:
    def __init__(self):
        self.events = {
            event: {"file": "", "enabled": False, "volume": 0.0} for event in KNOWN_EVENTS
        }

    def file_for(self, event: str):
        return None

    def volume_for(self, event: str) -> float:
        return 0.0

    def to_config(self) -> dict:
        return dict(self.events)

    def set(self, event: str, file: str, enabled=None, volume=None) -> None:
        return None


class NullSoundLibrary:
    def all_files(self) -> list[str]:
        return []

    def count(self) -> int:
        return 0

    def path_for(self, rel: str):
        return None


class NullSoundPlayer:
    def play_file(self, path, volume=1.0) -> None:
        return None

    preview = play_file

    def stop_preview(self) -> None:
        return None
