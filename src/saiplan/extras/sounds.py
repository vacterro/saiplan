"""Sounds (extras, spec 12). Sounds are ASSETS, never logic.

- Library: recursive .wav discovery over a LIST of roots, enumerated
  dynamically (no hardcoded count), forward-slash relative names.
- Roots, highest priority first: the user's personal sound pack (an absolute
  directory the user chose, stored in config), then the tracked
  redistributable `sounds/` folder that ships with the app. A personal pack
  is never copied into the repository or the release archive; it is read in
  place. Precedence means an operator who owns a richer personal library
  keeps every one of those files and their existing event mappings.
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
    "timer_finished": "timer_finished.wav",
    "pomodoro_work_done": "pomodoro_work_done.wav",
    "break_finished": "break_finished.wav",
    "due_reminder": "due_reminder.wav",
    "ticket_done": "ticket_done.wav",
    "blocked_warning": "blocked_warning.wav",
    "plan_completed": "plan_completed.wav",
    "click": "click.wav",
    "undo": "undo.wav",
}

KNOWN_EVENTS = tuple(DEFAULT_EVENTS.keys())


def _is_private_name(name: str) -> bool:
    """A `_`-prefixed file or folder stays out of the picker.

    The convention is borrowed from the personal-pack layout: a folder the
    operator marks private is never enumerated, so a scratch area cannot
    flood the sound dialog."""
    return name.startswith("_")


class SoundLibrary:
    """Enumerate sound assets across a personal pack and the shipped folder.

    ``sounds_dir`` is the packaged, redistributable root and always has the
    lowest priority; ``personal_dir`` is an optional absolute path chosen by
    the operator and has the highest priority. Both may be missing: an empty
    library is a valid state and must never raise.
    """

    def __init__(self, sounds_dir: Path, personal_dir: Path | str | None = None):
        self.sounds_dir = Path(sounds_dir).resolve()
        self.personal_dir = Path(personal_dir).expanduser().resolve() if personal_dir else None

    @property
    def roots(self) -> list[Path]:
        """Roots in resolution order, personal pack first."""
        roots = []
        if self.personal_dir is not None:
            roots.append(self.personal_dir)
        roots.append(self.sounds_dir)
        return roots

    def all_files(self) -> list[str]:
        """Relative forward-slash names, stable order, personal pack first.

        A name present in both roots appears once: the personal file wins,
        which is what "keep my library and my mappings" has to mean when the
        two libraries share a file name."""
        seen: dict[str, None] = {}
        for root in self.roots:
            if not root.is_dir():
                continue
            for path in sorted(root.rglob("*.wav")):
                rel = path.relative_to(root)
                if any(_is_private_name(part) for part in rel.parts):
                    continue
                seen.setdefault(rel.as_posix(), None)
        return list(seen)

    def count(self) -> int:
        return len(self.all_files())

    def path_for(self, rel: str) -> Path | None:
        """Resolve a relative name to a real file (or None if missing).

        Platform-neutral via PurePosixPath parts; the result MUST stay inside
        the root it was found in — `../` escapes are rejected outright."""
        if not rel:
            return None
        try:
            from pathlib import PurePosixPath

            parts = PurePosixPath(rel).parts
            if not parts or ".." in parts:
                return None
        except (ValueError, OSError):
            return None
        for root in self.roots:
            if not root.is_dir():
                continue
            try:
                candidate = root.joinpath(*parts).resolve()
            except (ValueError, OSError):
                continue
            if root not in candidate.parents and candidate != root:
                continue
            if candidate.is_file():
                return candidate
        return None



class SoundRegistry:
    """Per-event mapping, persisted through the app config dict.

    Stale names heal on load: if the mapped file no longer exists the event
    falls back to its default file, then to none — never to a crash. The name
    the operator originally chose is kept in ``requested`` so a personal pack
    added later can satisfy it again; healing never erases user intent.
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
            return {"file": default, "enabled": True, "volume": 1.0, "requested": ""}
        entry = events.get(event)
        if not isinstance(entry, dict):
            return {"file": default, "enabled": True, "volume": 1.0, "requested": ""}
        requested = entry.get("file")
        if not (isinstance(requested, str) and requested in self._available):
            requested = ""
        file = requested or default
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
            "requested": requested,
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
            entry["requested"] = file
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
