"""One theme registry, one token schema (spec 13, I12).

- themes/*.json is the ONLY token source; no palette values in source files.
- Golden Vintage (`goldenvintage`) is the default (I11).
- unknown/corrupt theme falls back safely to Golden Vintage.
- registry is Qt-free so validation tests run headless.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from .validation import validate_theme

logger = logging.getLogger("saiplan")

DEFAULT_THEME = "goldenvintage"


class ThemeError(Exception):
    pass


class Theme:
    def __init__(self, slug: str, label: str, tokens: dict, source: str | None = None):
        self.slug = slug
        self.label = label
        self.tokens = tokens
        self.source = source


# Last-resort palette used ONLY when even goldenvintage.json is missing or
# unreadable (e.g. a stripped install). It is not a shipped theme and never
# claims to be one — it exists so a broken theme asset cannot brick the app
# (I8). All 21 tokens present; the regular validation contract still applies
# to every shipped themes/*.json.
_EMERGENCY = {
    "background": "#1A1A1A",
    "backgroundSoft": "#2A2A2A",
    "surface": "#333333",
    "surfaceRaised": "#3D3D3D",
    "surfaceAlt": "#454545",
    "borderDark": "#000000",
    "borderHighlight": "#D6BE76",
    "bevelLight": "#655E4A",
    "borderMuted": "#555555",
    "textPrimary": "#C4BA9F",
    "textSecondary": "#8E8774",
    "textMuted": "#605C50",
    "accentTeal": "#008080",
    "accentTealDeep": "#004C4C",
    "success": "#4A7A20",
    "warning": "#7A7A20",
    "danger": "#7A2020",
    "dangerText": "#D45C5C",
    "selection": "#3D3D3D",
    "compareBack": "#141414",
    "link": "#D6BE76",
}


def emergency_theme() -> Theme:
    return Theme("goldenvintage", "Golden Vintage (emergency)", dict(_EMERGENCY))


class ThemeRegistry:
    def __init__(self, themes_dir: Path | str):
        self.themes_dir = Path(themes_dir)

    def _path_for(self, slug: str) -> Path:
        # canonical theme files may have a `.json` extension after the slug
        return self.themes_dir / f"{slug}.json"

    def list_themes(self) -> list[Theme]:
        """All valid themes, ordered by their `order` field."""
        out: list[Theme] = []
        for path in sorted(self.themes_dir.glob("*.json")):
            theme = self._try_load(path)
            if theme is not None:
                out.append(theme)
        out.sort(key=lambda t: getattr(t, "order", 999))
        return out

    def _try_load(self, path: Path) -> Theme | None:
        """Load one theme file. ANY failure returns None + a log line — the
        emergency fallback must survive a malformed theme, never crash on it."""
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if validate_theme(data):
                return None
            theme = Theme(
                data["slug"], data.get("label", data["slug"]), data["tokens"], data.get("source")
            )
            theme.order = data.get("order", 999)
            return theme
        except Exception as e:  # noqa: BLE001  (isolation by design, I8)
            logger.warning("theme %s rejected: %s", path.name, e)
            return None

    def get(self, slug: str | None) -> Theme:
        """Load `slug`, falling back to Golden Vintage on any failure. Only if
        even Golden Vintage is unreadable does it return the emergency palette —
        never a crash, never a silently wrong theme."""
        for candidate in (slug, DEFAULT_THEME):
            if not candidate:
                continue
            path = self._path_for(candidate)
            if path.exists():
                theme = self._try_load(path)
                if theme is not None:
                    return theme
        return emergency_theme()
