"""QSS generation from the token registry (Win95 grammar).

Wintage visual grammar (audited, spec 13): square corners, explicit borders,
raised buttons (bevelLight top/left, borderDark bottom/right), sunken fields
(inverted), clear pressed state (bevel inverted), zero radius, no animations,
no translucency. All values come from the theme tokens — never hardcoded.

Qt-free: produces a QSS string; no QApplication needed, so it is testable
headless.
"""

from __future__ import annotations


def _raised(tokens: dict) -> dict:
    """Raised (button) border colours: light top/left, dark bottom/right."""
    return {
        "top": tokens["bevelLight"],
        "left": tokens["bevelLight"],
        "bottom": tokens["borderDark"],
        "right": tokens["borderDark"],
        "top_color": tokens["borderHighlight"],
        "left_color": tokens["borderHighlight"],
        "bottom_color": tokens["borderDark"],
        "right_color": tokens["borderDark"],
    }


def _sunken(tokens: dict) -> dict:
    """Sunken (field) border colours: dark top/left, light bottom/right."""
    return {
        "top": tokens["borderDark"],
        "left": tokens["borderDark"],
        "bottom": tokens["borderHighlight"],
        "right": tokens["borderHighlight"],
        "top_color": tokens["borderDark"],
        "left_color": tokens["borderDark"],
        "bottom_color": tokens["borderHighlight"],
        "right_color": tokens["borderHighlight"],
    }


def _bevel(borders: dict, bg: str, color: str, width: int = 2) -> str:
    return (
        f"background: {bg}; color: {color}; "
        f"border: {width}px solid; "
        f"border-top-color: {borders['top']}; "
        f"border-left-color: {borders['left']}; "
        f"border-bottom-color: {borders['bottom']}; "
        f"border-right-color: {borders['right']}; "
        f"border-radius: 0px;"
    )


def build_qss(tokens: dict, scale: float = 1.0, font: str = "Verdana") -> str:
    """Render a full QSS stylesheet for one theme token set."""
    fs = max(8, round(12 * scale))
    pad = max(2, round(4 * scale))
    t = tokens
    b = _raised(t)
    f = _sunken(t)
    raised = _bevel(b, t["surfaceRaised"], t["textPrimary"])
    sunken = _bevel(f, t["backgroundSoft"], t["textPrimary"])
    pressed = _bevel(
        {
            "top": t["borderDark"],
            "left": t["borderDark"],
            "bottom": t["borderHighlight"],
            "right": t["borderHighlight"],
        },
        t["surfaceAlt"],
        t["textPrimary"],
    )

    return f"""
QWidget {{
    background: {t["background"]};
    color: {t["textPrimary"]};
    font-family: {font};
    font-size: {fs}px;
}}

QWidget::tooltip {{
    background: {t["surfaceRaised"]};
    color: {t["textPrimary"]};
    border: 2px solid {t["borderMuted"]};
    border-radius: 0px;
    padding: {pad}px;
}}

QMainWindow, QDialog {{
    background: {t["background"]};
}}

QMenuBar {{
    background: {t["surface"]};
    color: {t["textPrimary"]};
    border-bottom: 2px solid {t["borderDark"]};
}}

QMenuBar::item:selected {{
    background: {t["selection"]};
}}

QMenu {{
    background: {t["surface"]};
    color: {t["textPrimary"]};
    border: 2px outset {t["borderMuted"]};
}}

QMenu::item:selected {{
    background: {t["selection"]};
}}

QPushButton {{
    {raised}
    padding: {pad}px {round(pad * 2)}px;
    min-width: {round(60 * scale)}px;
    font-weight: bold;
}}

QPushButton:pressed {{
    {pressed}
}}

QPushButton:disabled {{
    color: {t["textMuted"]};
    background: {t["surface"]};
}}

QPushButton:default {{
    border-bottom-color: {t["accentTealDeep"]};
}}

QLineEdit, QTextEdit, QPlainTextEdit {{
    {sunken}
    padding: {max(1, round(pad * 0.6))}px;
    selection-background-color: {t["selection"]};
    selection-color: {t["textPrimary"]};
}}

QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus {{
    border-color: {t["borderHighlight"]};
}}

QComboBox {{
    {raised}
    padding: {pad}px;
}}

QComboBox QAbstractItemView {{
    background: {t["backgroundSoft"]};
    color: {t["textPrimary"]};
    border: 2px inset {t["borderDark"]};
    selection-background-color: {t["selection"]};
}}

QCheckBox, QRadioButton {{
    color: {t["textPrimary"]};
    spacing: {pad}px;
}}

QCheckBox::indicator, QRadioButton::indicator {{
    width: {round(14 * scale)}px;
    height: {round(14 * scale)}px;
    background: {t["backgroundSoft"]};
    border: 2px solid {t["borderDark"]};
    border-top-color: {t["borderDark"]};
    border-left-color: {t["borderDark"]};
    border-bottom-color: {t["borderHighlight"]};
    border-right-color: {t["borderHighlight"]};
}}

QCheckBox::indicator:checked {{
    background: {t["backgroundSoft"]};
    border: 2px inset {t["borderDark"]};
}}

QListWidget, QTreeWidget, QTableView, QTableWidget {{
    background: {t["backgroundSoft"]};
    alternate-background-color: {t["surfaceAlt"]};
    color: {t["textPrimary"]};
    {sunken}
}}

QListWidget::item, QTreeWidget::item {{
    padding: {pad}px;
}}

QListWidget::item:selected, QTreeWidget::item:selected,
QTableWidget::item:selected {{
    background: {t["selection"]};
    color: {t["textPrimary"]};
}}

QListWidget::item:hover, QTreeWidget::item:hover {{
    background: {t["surfaceAlt"]};
}}

QHeaderView::section {{
    background: {t["surface"]};
    color: {t["textPrimary"]};
    border: 2px outset {t["surfaceRaised"]};
    border-top-color: {t["bevelLight"]};
    border-left-color: {t["bevelLight"]};
    border-bottom-color: {t["borderDark"]};
    border-right-color: {t["borderDark"]};
    padding: {pad}px;
    font-weight: bold;
}}

QTabWidget::pane {{
    border: 2px solid {t["borderDark"]};
}}

QTabBar::tab {{
    background: {t["surface"]};
    color: {t["textSecondary"]};
    border: 2px outset {t["surfaceRaised"]};
    border-top-color: {t["bevelLight"]};
    border-left-color: {t["bevelLight"]};
    border-bottom-color: {t["borderDark"]};
    border-right-color: {t["borderDark"]};
    padding: {pad}px {round(pad * 2)}px;
}}

QTabBar::tab:selected {{
    background: {t["surfaceRaised"]};
    color: {t["textPrimary"]};
    border-bottom-color: {t["surfaceRaised"]};
}}

QScrollBar:vertical {{
    background: {t["surface"]};
    width: {round(16 * scale)}px;
    border: 2px outset {t["surfaceRaised"]};
}}

QScrollBar::handle:vertical {{
    background: {t["surfaceRaised"]};
    border: 2px outset {t["surfaceRaised"]};
    border-top-color: {t["bevelLight"]};
    border-left-color: {t["bevelLight"]};
    border-bottom-color: {t["borderDark"]};
    border-right-color: {t["borderDark"]};
    min-height: 20px;
}}

QScrollBar:horizontal {{
    background: {t["surface"]};
    height: {round(16 * scale)}px;
    border: 2px outset {t["surfaceRaised"]};
}}

QScrollBar::handle:horizontal {{
    background: {t["surfaceRaised"]};
    border: 2px outset {t["surfaceRaised"]};
    border-top-color: {t["bevelLight"]};
    border-left-color: {t["bevelLight"]};
    border-bottom-color: {t["borderDark"]};
    border-right-color: {t["borderDark"]};
    min-width: 20px;
}}

QScrollBar::add-line, QScrollBar::sub-line {{
    background: {t["surface"]};
    border: 2px outset {t["surfaceRaised"]};
    height: {round(14 * scale)}px;
    width: {round(14 * scale)}px;
}}

QProgressBar {{
    background: {t["backgroundSoft"]};
    color: {t["textPrimary"]};
    border: 2px inset {t["borderDark"]};
    border-radius: 0px;
    text-align: center;
}}

QProgressBar::chunk {{
    background: {t["accentTeal"]};
    border: 1px solid {t["accentTealDeep"]};
}}

QSplitter::handle {{
    background: {t["borderDark"]};
}}

QStatusBar {{
    background: {t["surface"]};
    color: {t["textSecondary"]};
    border-top: 2px solid {t["borderDark"]};
}}

QStatusBar::item {{
    border: none;
}}

QLabel {{
    background: transparent;
    color: {t["textPrimary"]};
}}

QLabel#sectionTitle {{
    color: {t["textSecondary"]};
    font-weight: bold;
}}

QToolBar {{
    background: {t["surface"]};
    border-bottom: 2px solid {t["borderDark"]};
    spacing: {pad}px;
}}
"""
