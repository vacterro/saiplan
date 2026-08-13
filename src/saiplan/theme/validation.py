"""Theme validation: Wintage 21-token schema + WCAG AA gate.

Canonical contract (audited from Wintage theme-schema.json / theme-schema.js,
see docs/REFERENCE_AUDIT.md):
- a theme is `{slug, label, order, source?, tokens: {21 tokens, all #rrggbb}}`
- every shipped theme carries ALL 21 tokens (I12)
- WCAG AA >= 4.5:1 for textPrimary / textSecondary / link vs backgroundSoft
- pack rules: slug lowercase alnum, filename == slug, unique slug/label,
  no apostrophe in label

HARD RULE: `validate_theme(any JSON value) -> list[str]` MUST never raise.
The emergency fallback depends on validation being unable to crash on
arbitrary input (a token that is an int, a list, null, missing, broken hex…).
"""

from __future__ import annotations

import json
from pathlib import Path

REQUIRED_TOKENS = frozenset(
    {
        "background",
        "backgroundSoft",
        "surface",
        "surfaceRaised",
        "surfaceAlt",
        "borderDark",
        "borderHighlight",
        "bevelLight",
        "borderMuted",
        "textPrimary",
        "textSecondary",
        "textMuted",
        "accentTeal",
        "accentTealDeep",
        "success",
        "warning",
        "danger",
        "dangerText",
        "selection",
        "compareBack",
        "link",
    }
)

WCAG_ROLES = ("textPrimary", "textSecondary", "link")

HEX_RE = "^#[0-9a-fA-F]{6}$"


def _is_hex_colour(value) -> bool:
    if not isinstance(value, str) or len(value) != 7 or value[0] != "#":
        return False
    try:
        int(value[1:], 16)
        return True
    except ValueError:
        return False


def hex_to_rgb(value: str) -> tuple[int, int, int]:
    value = value.lstrip("#")
    return tuple(int(value[i : i + 2], 16) for i in (0, 2, 4))


def relative_luminance(rgb: tuple[int, int, int]) -> float:
    def chan(c: float) -> float:
        c /= 255.0
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = (chan(x) for x in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(a: str, b: str) -> float:
    l1, l2 = relative_luminance(hex_to_rgb(a)), relative_luminance(hex_to_rgb(b))
    hi, lo = max(l1, l2), min(l1, l2)
    return (hi + 0.05) / (lo + 0.05)


def validate_theme(data) -> list[str]:
    """Return a list of problems. Empty list == valid theme.

    Accepts ANY JSON-decoded value; never raises. Only hex-validated tokens
    reach the WCAG contrast computation."""
    problems: list[str] = []
    if not isinstance(data, dict):
        return ["theme is not a JSON object"]

    slug = data.get("slug")
    label = data.get("label")
    tokens = data.get("tokens")

    if (
        not isinstance(slug, str)
        or not slug.islower()
        or not slug.replace("-", "").replace("_", "").isalnum()
    ):
        problems.append(f"slug {slug!r} must be lowercase alphanumeric")
    if not isinstance(label, str) or "'" in label:
        problems.append(f"label {label!r} must be a string without apostrophes")
    if not isinstance(tokens, dict):
        problems.append("missing tokens object")
        return problems

    missing = REQUIRED_TOKENS - set(tokens)
    if missing:
        problems.append(f"missing tokens: {', '.join(sorted(missing))}")
    extra = set(tokens) - REQUIRED_TOKENS
    if extra:
        problems.append(f"unknown tokens: {', '.join(sorted(extra))}")

    for key in REQUIRED_TOKENS:
        value = tokens.get(key)
        if not _is_hex_colour(value):
            problems.append(f"token {key} is not #rrggbb: {value!r}")

    # WCAG gate only for tokens that passed strict hex validation
    bg = tokens.get("backgroundSoft")
    if _is_hex_colour(bg):
        for role in WCAG_ROLES:
            fg = tokens.get(role)
            if not _is_hex_colour(fg):
                continue
            ratio = contrast_ratio(fg, bg)
            if ratio < 4.5:
                problems.append(
                    f"WCAG AA failed: {role} ({fg}) vs backgroundSoft ({bg}) "
                    f"is {ratio:.2f}:1, floor is 4.5:1"
                )
    return problems


def validate_theme_file(path: Path) -> list[str]:
    """Validate one themes/*.json file, including filename==slug. Never raises."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, UnicodeDecodeError) as e:
        return [f"cannot read theme file: {e}"]
    problems = validate_theme(data)
    if isinstance(data, dict) and path.stem != data.get("slug"):
        problems.append(f"filename {path.name!r} must equal slug {data.get('slug')!r}")
    return problems


def check_shipped_themes(themes_dir) -> tuple[int, list[str]]:
    """Validate every themes/*.json. Returns (valid_count, all_problems)."""
    valid, all_problems = 0, []
    for path in sorted(Path(themes_dir).glob("*.json")):
        problems = validate_theme_file(path)
        if problems:
            all_problems.append(f"{path.name}: {'; '.join(problems)}")
        else:
            valid += 1
    return valid, all_problems
