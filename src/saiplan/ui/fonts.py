"""Non-antialiased font setup (vintage grammar: zero AA text).

Qt-specific by design — keep out of the Qt-free theme layer so headless
tests of QSS generation stay dependency-free.
"""

from __future__ import annotations

from PyQt6.QtGui import QFont


def no_antialias_font(base: QFont) -> QFont:
    """Return a copy of `base` tuned for crisp pixel text (no AA).

    PreferNoAntialias disables glyph smoothing on raster platforms;
    PreferFullHinting sharpens stems to the pixel grid.
    """
    font = QFont(base)
    font.setStyleStrategy(QFont.StyleStrategy.NoAntialias)
    font.setHintingPreference(QFont.HintingPreference.PreferFullHinting)
    return font
