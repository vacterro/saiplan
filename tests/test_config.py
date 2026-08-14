"""Config per-key validation (spec 18): a broken value falls back to that
key's default; one bad setting never bricks startup."""

import json

from saiplan.core.config import DEFAULTS, Config


def _write(tmp_path, data):
    path = tmp_path / "config.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_wrong_types_fall_back_per_key(tmp_path):
    path = _write(
        tmp_path,
        {
            "theme": 123,
            "scale": "banana",
            "single_focus": "yes",
            "snapshot_keep": "many",
            "sound_volume": "loud",
            "always_on_top": "true",
            "mirror_enabled": 1,
            "recent_plans": "nope",
            "pinned_plans": [1, 2],
            "sound_events": [],
            "window_geometry": 42,
        },
    )
    c = Config(path)
    c.load()
    assert c.get("theme") == DEFAULTS["theme"] == "goldenvintage"
    assert c.get("scale") == 1.0
    assert c.get("single_focus") is True
    assert c.get("snapshot_keep") == 14
    assert c.get("sound_volume") == 5
    assert c.get("always_on_top") is False
    assert c.get("mirror_enabled") is False
    assert c.get("recent_plans") == []
    assert c.get("pinned_plans") == []
    assert c.get("sound_events") == {}
    assert c.get("window_geometry") == ""


def test_out_of_range_values_fall_back(tmp_path):
    c = Config(_write(tmp_path, {"scale": 99.0, "snapshot_keep": 0, "sound_volume": 500}))
    c.load()
    assert c.get("scale") == 1.0
    assert c.get("snapshot_keep") == 14
    assert c.get("sound_volume") == 5


def test_non_finite_scale_rejected(tmp_path):
    import json as j

    path = tmp_path / "config.json"
    path.write_text(j.dumps({"scale": float("inf")}), encoding="utf-8")
    c = Config(path)
    c.load()
    assert c.get("scale") == 1.0


def test_valid_values_pass_through(tmp_path):
    c = Config(
        _write(
            tmp_path,
            {"scale": 1.25, "snapshot_keep": 30, "sound_volume": 8, "theme": "nord"},
        )
    )
    c.load()
    assert c.get("scale") == 1.25
    assert c.get("snapshot_keep") == 30
    assert c.get("sound_volume") == 8
    assert c.get("theme") == "nord"


def test_non_dict_config_falls_back_entirely(tmp_path):
    path = tmp_path / "config.json"
    path.write_text("[1,2,3]", encoding="utf-8")
    c = Config(path)
    c.load()
    assert c.data == DEFAULTS


def test_corrupt_json_falls_back(tmp_path):
    path = tmp_path / "config.json"
    path.write_text("{ not json", encoding="utf-8")
    c = Config(path)
    c.load()
    assert c.data == DEFAULTS


def test_save_keeps_only_known_keys(tmp_path):
    c = Config(tmp_path / "config.json")
    c.set("theme", "oled")
    c.set("bogus_key", "should be dropped")
    c.save()
    loaded = json.loads((tmp_path / "config.json").read_text(encoding="utf-8"))
    assert "bogus_key" not in loaded
    assert loaded["theme"] == "oled"


def test_wip_limits_invalid_values_dropped(tmp_path):
    c = Config(
        _write(
            tmp_path,
            {"wip_limits": {"DOING": "lots", "TODO": 0, "DONE": -3, "BLOCKED": 2, 7: 4}},
        )
    )
    c.load()
    assert c.get("wip_limits") == {"BLOCKED": 2}  # only valid positive ints kept


def test_wip_limits_non_dict_falls_back(tmp_path):
    c = Config(_write(tmp_path, {"wip_limits": [1, 2, 3]}))
    c.load()
    assert c.get("wip_limits") == {}


def test_wip_limits_survive_restart(tmp_path):
    path = tmp_path / "config.json"
    c = Config(path)
    c.set("wip_limits", {"DOING": 2, "TODO": 5})
    c.save()
    c2 = Config(path)
    c2.load()
    assert c2.get("wip_limits") == {"DOING": 2, "TODO": 5}
