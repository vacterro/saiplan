"""Themes (spec 13, 19): every shipped theme loads, tokens complete, WCAG AA,
Golden Vintage default + fallback, runtime switching."""

import json
from pathlib import Path

from saiplan.theme.loader import build_qss
from saiplan.theme.registry import DEFAULT_THEME, ThemeRegistry
from saiplan.theme.validation import (
    REQUIRED_TOKENS,
    check_shipped_themes,
    contrast_ratio,
    validate_theme,
)

THEMES_DIR = Path(__file__).resolve().parents[1] / "themes"


def test_default_is_golden_vintage():
    assert DEFAULT_THEME == "goldenvintage"


def test_every_shipped_theme_valid():
    valid, problems = check_shipped_themes(THEMES_DIR)
    assert problems == [], problems
    assert valid == 16


def test_registry_lists_all_themes():
    reg = ThemeRegistry(THEMES_DIR)
    slugs = {t.slug for t in reg.list_themes()}
    assert len(slugs) == 16
    assert "goldenvintage" in slugs


def test_all_required_tokens_present_in_every_theme():
    for path in THEMES_DIR.glob("*.json"):
        data = json.loads(path.read_text(encoding="utf-8"))
        assert REQUIRED_TOKENS <= set(data["tokens"]), path.name


def test_theme_tokens_are_hex():
    for path in THEMES_DIR.glob("*.json"):
        data = json.loads(path.read_text(encoding="utf-8"))
        for key, value in data["tokens"].items():
            assert len(value) == 7 and value[0] == "#", f"{path.name}:{key}"


def test_wcag_aa_gate_passes_all_shipped():
    failures = []
    for path in THEMES_DIR.glob("*.json"):
        data = json.loads(path.read_text(encoding="utf-8"))
        bg = data["tokens"]["backgroundSoft"]
        for role in ("textPrimary", "textSecondary", "link"):
            fg = data["tokens"][role]
            ratio = contrast_ratio(fg, bg)
            if ratio < 4.5:
                failures.append(f"{path.name}:{role} {ratio:.2f}:1")
    assert failures == [], failures


def test_golden_vintage_loads():
    reg = ThemeRegistry(THEMES_DIR)
    theme = reg.get("goldenvintage")
    assert theme.label == "Golden Vintage"
    assert set(theme.tokens) == REQUIRED_TOKENS


def test_unknown_theme_falls_back_to_golden():
    reg = ThemeRegistry(THEMES_DIR)
    theme = reg.get("no-such-theme")
    assert theme.slug == "goldenvintage"


def test_corrupt_theme_falls_back(tmp_path):
    (tmp_path / "broken.json").write_text("{ not json", encoding="utf-8")
    (tmp_path / "badpacks.json").write_text(
        json.dumps({"slug": "badpacks", "label": "Bad", "tokens": {"background": "x"}}),
        encoding="utf-8",
    )
    reg = ThemeRegistry(tmp_path)
    # no valid theme anywhere -> emergency palette, never a crash
    theme = reg.get("broken")
    assert theme.slug == "goldenvintage"
    assert set(theme.tokens) == REQUIRED_TOKENS


def test_runtime_switching_produces_different_qss():
    reg = ThemeRegistry(THEMES_DIR)
    dark = reg.get("goldenvintage")
    light = reg.get("vintageclassic")
    assert dark.tokens["background"] != light.tokens["background"]
    qss_dark = build_qss(dark.tokens)
    qss_light = build_qss(light.tokens)
    assert qss_dark != qss_light
    # both speak Win95 grammar: square corners and raised buttons
    assert "border-radius: 0px" in qss_dark
    assert "bevelLight" not in qss_dark  # resolved, not templated
    assert "font-size" in qss_dark


def test_qss_respects_scale():
    tokens = ThemeRegistry(THEMES_DIR).get("goldenvintage").tokens
    small = build_qss(tokens, scale=0.8)
    large = build_qss(tokens, scale=1.5)
    assert small != large
    assert "font-size" in small


def test_schema_contract_matches_wintage():
    """The registry contract equals the audited Wintage schema."""
    data = json.loads((THEMES_DIR / "goldenvintage.json").read_text(encoding="utf-8"))
    assert set(data["tokens"]) == REQUIRED_TOKENS


def test_validate_theme_reports_problems():
    problems = validate_theme({"slug": "Bad Label", "label": "O'Brian", "tokens": {}})
    assert any("slug" in p for p in problems)
    assert any("apostrophe" in p for p in problems)
    assert any("missing tokens" in p for p in problems)
