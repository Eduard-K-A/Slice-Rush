"""Typed config loading for Slice Rush.

Every class receives its configuration as a typed dataclass (dependency
injection) — nothing else in the codebase reads YAML or global state.

Policy (plan section 6): keys under `camera`, `detection`, `persistence`
are hardware/operations-critical and FAIL FAST if missing. Keys under
`game`, `display`, `effects`, `audio`, `assets` fall back to safe defaults
(logged) if absent.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import yaml

log = logging.getLogger(__name__)


class ConfigError(Exception):
    """Raised when a required configuration key is missing or invalid."""


# --------------------------------------------------------------------------- camera


@dataclass
class CameraConfig:
    device_index: int
    backend: str
    fourcc: str
    frame_width: int
    frame_height: int
    target_fps: int
    manual_exposure: bool
    auto_exposure_off_value: float
    exposure_value: float
    gain: float
    disable_auto_white_balance: bool
    white_balance_temperature: Optional[int]
    mirror: bool
    reconnect_after_failures: int
    reconnect_cooldown_seconds: float


# --------------------------------------------------------------------------- detection


@dataclass
class MarkerConfig:
    name: str
    hsv_lower: Tuple[int, int, int]
    hsv_upper: Tuple[int, int, int]
    min_area_px: float
    max_area_px: float


@dataclass
class MorphologyConfig:
    open_kernel: int
    open_iterations: int
    close_kernel: int
    close_iterations: int


@dataclass
class DetectionConfig:
    markers: List[MarkerConfig]
    blur_kernel: int
    morphology: MorphologyConfig


# --------------------------------------------------------------------------- hand detection


@dataclass
class HandDetectionConfig:
    landmark_index: int = 8                                          # 8=index fingertip, 9=middle MCP, 0=wrist
    min_detection_confidence: float = 0.7
    min_tracking_confidence: float = 0.5
    max_num_hands: int = 1
    model_path: str = "assets/models/hand_landmarker.task"          # auto-downloaded on first run


# --------------------------------------------------------------------------- tracking


@dataclass
class KalmanConfig:
    process_noise: float
    measurement_noise: float
    max_missed_frames: int


@dataclass
class TrackingConfig:
    kalman: KalmanConfig


# --------------------------------------------------------------------------- game


@dataclass
class TimersConfig:
    countdown_seconds: float = 3
    round_duration_seconds: float = 10
    round_transition_seconds: float = 2.0
    game_over_seconds: float = 2.5
    score_submit_timeout_seconds: float = 20


@dataclass
class ScoreTargetConfig:
    base: int = 40
    increment: int = 40


@dataclass
class DifficultyConfig:
    base_spawn_interval_seconds: float = 1.2
    spawn_interval_decay_per_round: float = 0.08
    min_spawn_interval_seconds: float = 0.35
    base_bad_object_ratio: float = 0.15
    bad_object_ratio_increment_per_round: float = 0.03
    max_bad_object_ratio: float = 0.5
    spawn_count_per_interval: int = 2          # how many entities to spawn each interval trigger


@dataclass
class ScoringConfig:
    fruit_points: Dict[str, int] = field(
        default_factory=lambda: {
            "apple": 10,
            "banana": 10,
            "strawberry": 10,
            "pineapple": 15,
            "watermelon": 20,
        }
    )
    bad_object_types: List[str] = field(default_factory=lambda: ["bomb", "rock"])


@dataclass
class ComboConfig:
    combo_bonus_threshold: int = 5
    combo_bonus_points: int = 0


@dataclass
class PhysicsConfig:
    gravity_px_s2: float = 900
    fall_speed_min_px_s: float = 40
    fall_speed_max_px_s: float = 120
    horizontal_speed_max_px_s: float = 60
    spin_max_deg_s: float = 180
    fall_speed_scale_per_round: float = 0.12   # multiply fall speed by (1 + scale*(round-1))


@dataclass
class SliceConfig:
    min_speed_px_s: float = 350
    trail_max_points: int = 6


@dataclass
class GameConfig:
    timers: TimersConfig = field(default_factory=TimersConfig)
    starting_hearts: int = 3
    score_target: ScoreTargetConfig = field(default_factory=ScoreTargetConfig)
    difficulty: DifficultyConfig = field(default_factory=DifficultyConfig)
    scoring: ScoringConfig = field(default_factory=ScoringConfig)
    combo: ComboConfig = field(default_factory=ComboConfig)
    physics: PhysicsConfig = field(default_factory=PhysicsConfig)
    slice: SliceConfig = field(default_factory=SliceConfig)


# --------------------------------------------------------------------------- display / effects / audio / assets


@dataclass
class DisplayConfig:
    window_width: int = 1280
    window_height: int = 720
    fullscreen: bool = True
    fps_cap: int = 60
    show_debug_overlay: bool = False


@dataclass
class EffectsConfig:
    screen_shake_enabled: bool = True
    particles_per_slice: int = 14
    max_particles: int = 600
    score_popup_seconds: float = 0.8


@dataclass
class AudioConfig:
    enabled: bool = True
    volume: float = 0.8


@dataclass
class AssetsConfig:
    sprites_dir: str = "assets/sprites"
    sounds_dir: str = "assets/sounds"
    entity_sprite_px: int = 96


# --------------------------------------------------------------------------- persistence


@dataclass
class PersistenceConfig:
    db_path: str
    leaderboard_top_n: int
    idle_timeout_seconds: float
    name_entry: bool
    name_max_chars: int


# --------------------------------------------------------------------------- top level


@dataclass
class AppConfig:
    camera: CameraConfig
    detection_mode: str               # "hsv" or "hand"
    detection: Optional[DetectionConfig]
    hand_detection: Optional[HandDetectionConfig]
    tracking: TrackingConfig
    game: GameConfig
    display: DisplayConfig
    effects: EffectsConfig
    audio: AudioConfig
    assets: AssetsConfig
    persistence: PersistenceConfig


def _require(section: Dict[str, Any], key: str, section_name: str) -> Any:
    if key not in section:
        raise ConfigError(f"config.yaml is missing required key '{section_name}.{key}'")
    return section[key]


def _require_section(raw: Dict[str, Any], name: str) -> Dict[str, Any]:
    if name not in raw or raw[name] is None:
        raise ConfigError(f"config.yaml is missing required section '{name}'")
    return raw[name]


def _optional_dataclass(cls, raw: Optional[Dict[str, Any]], section_name: str):
    """Build a defaults-capable dataclass from a possibly-partial dict."""
    raw = raw or {}
    known = {f: raw[f] for f in cls.__dataclass_fields__ if f in raw}
    missing = [f for f in cls.__dataclass_fields__ if f not in raw]
    if missing:
        log.info("config: section '%s' using defaults for %s", section_name, missing)
    return cls(**known)


def load_config(path: str) -> AppConfig:
    with open(path, "r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)
    if not isinstance(raw, dict):
        raise ConfigError(f"config file {path!r} did not parse to a mapping")

    # --- camera (fail fast) ---
    cam = _require_section(raw, "camera")
    camera = CameraConfig(
        device_index=_require(cam, "device_index", "camera"),
        backend=_require(cam, "backend", "camera"),
        fourcc=_require(cam, "fourcc", "camera"),
        frame_width=_require(cam, "frame_width", "camera"),
        frame_height=_require(cam, "frame_height", "camera"),
        target_fps=_require(cam, "target_fps", "camera"),
        manual_exposure=_require(cam, "manual_exposure", "camera"),
        auto_exposure_off_value=_require(cam, "auto_exposure_off_value", "camera"),
        exposure_value=_require(cam, "exposure_value", "camera"),
        gain=_require(cam, "gain", "camera"),
        disable_auto_white_balance=_require(cam, "disable_auto_white_balance", "camera"),
        white_balance_temperature=cam.get("white_balance_temperature"),
        mirror=_require(cam, "mirror", "camera"),
        reconnect_after_failures=_require(cam, "reconnect_after_failures", "camera"),
        reconnect_cooldown_seconds=_require(cam, "reconnect_cooldown_seconds", "camera"),
    )

    # --- detection_mode ---
    detection_mode = raw.get("detection_mode", "hsv")
    if detection_mode not in ("hsv", "hand"):
        raise ConfigError(f"config.yaml: 'detection_mode' must be 'hsv' or 'hand', got {detection_mode!r}")

    # --- HSV detection (fail fast when mode is hsv) ---
    detection: Optional[DetectionConfig] = None
    if detection_mode == "hsv":
        det = _require_section(raw, "detection")
        raw_markers = _require(det, "markers", "detection")
        if not raw_markers:
            raise ConfigError("config.yaml: 'detection.markers' must list at least the 'tip' marker")
        markers = []
        for m in raw_markers:
            markers.append(
                MarkerConfig(
                    name=_require(m, "name", "detection.markers[]"),
                    hsv_lower=tuple(_require(m, "hsv_lower", "detection.markers[]")),
                    hsv_upper=tuple(_require(m, "hsv_upper", "detection.markers[]")),
                    min_area_px=_require(m, "min_area_px", "detection.markers[]"),
                    max_area_px=_require(m, "max_area_px", "detection.markers[]"),
                )
            )
        if not any(m.name == "tip" for m in markers):
            raise ConfigError("config.yaml: 'detection.markers' must include a marker named 'tip'")
        morph_raw = _require(det, "morphology", "detection")
        morphology = MorphologyConfig(
            open_kernel=_require(morph_raw, "open_kernel", "detection.morphology"),
            open_iterations=_require(morph_raw, "open_iterations", "detection.morphology"),
            close_kernel=_require(morph_raw, "close_kernel", "detection.morphology"),
            close_iterations=_require(morph_raw, "close_iterations", "detection.morphology"),
        )
        detection = DetectionConfig(
            markers=markers,
            blur_kernel=_require(det, "blur_kernel", "detection"),
            morphology=morphology,
        )

    # --- hand detection (defaults allowed when mode is hand) ---
    hand_detection: Optional[HandDetectionConfig] = None
    if detection_mode == "hand":
        hand_detection = _optional_dataclass(
            HandDetectionConfig, raw.get("hand_detection"), "hand_detection"
        )

    # --- tracking (defaults allowed) ---
    trk = raw.get("tracking") or {}
    tracking = TrackingConfig(
        kalman=_optional_dataclass(KalmanConfig, (trk.get("kalman") or {
            "process_noise": 1.0e-2,
            "measurement_noise": 1.0e-1,
            "max_missed_frames": 8,
        }), "tracking.kalman")
        if trk.get("kalman")
        else KalmanConfig(process_noise=1.0e-2, measurement_noise=1.0e-1, max_missed_frames=8)
    )

    # --- game (defaults allowed) ---
    g = raw.get("game") or {}
    game = GameConfig(
        timers=_optional_dataclass(TimersConfig, g.get("timers"), "game.timers"),
        starting_hearts=g.get("starting_hearts", 3),
        score_target=_optional_dataclass(ScoreTargetConfig, g.get("score_target"), "game.score_target"),
        difficulty=_optional_dataclass(DifficultyConfig, g.get("difficulty"), "game.difficulty"),
        scoring=_optional_dataclass(ScoringConfig, g.get("scoring"), "game.scoring"),
        combo=_optional_dataclass(ComboConfig, g.get("combo"), "game.combo"),
        physics=_optional_dataclass(PhysicsConfig, g.get("physics"), "game.physics"),
        slice=_optional_dataclass(SliceConfig, g.get("slice"), "game.slice"),
    )

    display = _optional_dataclass(DisplayConfig, raw.get("display"), "display")
    effects = _optional_dataclass(EffectsConfig, raw.get("effects"), "effects")
    audio = _optional_dataclass(AudioConfig, raw.get("audio"), "audio")
    assets = _optional_dataclass(AssetsConfig, raw.get("assets"), "assets")

    # --- persistence (fail fast) ---
    per = _require_section(raw, "persistence")
    persistence = PersistenceConfig(
        db_path=_require(per, "db_path", "persistence"),
        leaderboard_top_n=_require(per, "leaderboard_top_n", "persistence"),
        idle_timeout_seconds=_require(per, "idle_timeout_seconds", "persistence"),
        name_entry=_require(per, "name_entry", "persistence"),
        name_max_chars=_require(per, "name_max_chars", "persistence"),
    )

    return AppConfig(
        camera=camera,
        detection_mode=detection_mode,
        detection=detection,
        hand_detection=hand_detection,
        tracking=tracking,
        game=game,
        display=display,
        effects=effects,
        audio=audio,
        assets=assets,
        persistence=persistence,
    )


def save_config(path: str, updates: dict) -> None:
    """Deep-merge `updates` into the YAML at `path` and write back.
    Only keys present in `updates` are touched; everything else is preserved."""
    import copy
    with open(path, "r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)

    def _deep_merge(base: dict, patch: dict) -> dict:
        result = copy.deepcopy(base)
        for k, v in patch.items():
            if isinstance(v, dict) and isinstance(result.get(k), dict):
                result[k] = _deep_merge(result[k], v)
            else:
                result[k] = v
        return result

    merged = _deep_merge(raw, updates)
    with open(path, "w", encoding="utf-8") as fh:
        yaml.safe_dump(merged, fh, default_flow_style=False, sort_keys=False)
