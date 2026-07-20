import pytest
import yaml

from src.config_loader import ConfigError, load_config

CONFIG_PATH = "config/config.yaml"


def test_shipped_config_loads():
    cfg = load_config(CONFIG_PATH)
    assert cfg.game.timers.round_duration_seconds == 10
    assert cfg.camera.backend == "dshow"
    assert cfg.camera.fourcc == "MJPG"
    assert cfg.game.score_target.base == 40
    assert cfg.game.scoring.fruit_points["watermelon"] == 20
    assert cfg.persistence.leaderboard_top_n == 10
    assert cfg.detection_mode in ("hsv", "hand")
    if cfg.detection_mode == "hsv":
        assert any(m.name == "tip" for m in cfg.detection.markers)
    else:
        assert cfg.hand_detection is not None


def test_missing_required_camera_key_fails_fast(tmp_path):
    with open(CONFIG_PATH, "r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)
    del raw["camera"]["device_index"]
    p = tmp_path / "broken.yaml"
    p.write_text(yaml.safe_dump(raw), encoding="utf-8")
    with pytest.raises(ConfigError, match="camera.device_index"):
        load_config(str(p))


def test_missing_gameplay_section_uses_defaults(tmp_path):
    with open(CONFIG_PATH, "r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)
    del raw["game"]
    del raw["effects"]
    p = tmp_path / "partial.yaml"
    p.write_text(yaml.safe_dump(raw), encoding="utf-8")
    cfg = load_config(str(p))
    assert cfg.game.timers.round_duration_seconds == 10
    assert cfg.effects.particles_per_slice == 14


def test_missing_tip_marker_fails_hsv_mode(tmp_path):
    with open(CONFIG_PATH, "r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)
    raw["detection_mode"] = "hsv"
    raw["detection"]["markers"][0]["name"] = "not_tip"
    p = tmp_path / "no_tip.yaml"
    p.write_text(yaml.safe_dump(raw), encoding="utf-8")
    with pytest.raises(ConfigError, match="tip"):
        load_config(str(p))


def test_invalid_detection_mode_fails(tmp_path):
    with open(CONFIG_PATH, "r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)
    raw["detection_mode"] = "laser"
    p = tmp_path / "bad_mode.yaml"
    p.write_text(yaml.safe_dump(raw), encoding="utf-8")
    with pytest.raises(ConfigError, match="detection_mode"):
        load_config(str(p))


def test_hand_detection_mode_loads(tmp_path):
    with open(CONFIG_PATH, "r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)
    raw["detection_mode"] = "hand"
    p = tmp_path / "hand_mode.yaml"
    p.write_text(yaml.safe_dump(raw), encoding="utf-8")
    cfg = load_config(str(p))
    assert cfg.detection_mode == "hand"
    assert cfg.detection is None
    assert cfg.hand_detection is not None
