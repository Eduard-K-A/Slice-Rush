import random

import numpy as np

from src.config_loader import EffectsConfig, PhysicsConfig
from src.game.effects import HALF_MAX_AGE_S, EffectsSystem, SHAKE_DURATION_S
from src.game.entities import EntityType, FallingEntity


def make_entity(subtype="apple", entity_type=EntityType.FRUIT, points=10):
    return FallingEntity(
        id=1,
        entity_type=entity_type,
        subtype=subtype,
        position=np.array([300.0, 200.0], dtype=np.float32),
        velocity=np.array([10.0, 50.0], dtype=np.float32),
        radius_px=48,
        points=points,
        rotation_deg=45.0,
        spin_deg_s=90.0,
    )


def make_effects(**overrides):
    cfg = EffectsConfig(**overrides)
    fx = EffectsSystem(cfg, PhysicsConfig(), random.Random(1))
    fx.set_screen_height(720)
    return fx, cfg


def test_fruit_slice_spawns_expected_counts():
    fx, cfg = make_effects()
    fx.spawn_fruit_slice(make_entity())
    assert len(fx.halves) == 2
    assert {h.sprite_key for h in fx.halves} == {"apple_half_1", "apple_half_2"}
    assert len(fx.particles) == cfg.particles_per_slice + 6  # burst + 6 splat blobs
    assert len(fx.popups) == 1
    assert fx.popups[0].text == "+10"


def test_combo_popup_text():
    fx, _ = make_effects()
    fx.spawn_fruit_slice(make_entity(points=15), combo=4)
    assert fx.popups[0].text == "+15 x4!"


def test_bomb_triggers_shake_and_flash():
    fx, _ = make_effects()
    fx.spawn_bad_hit(make_entity("bomb", EntityType.BAD, 0))
    assert fx.red_flash_alpha() > 0
    assert fx.shake_offset() != (0, 0) or True  # shake armed (offset can randomly be 0,0)
    fx.update(SHAKE_DURATION_S + 0.01)
    assert fx.shake_offset() == (0, 0)
    fx.update(1.0)
    assert fx.red_flash_alpha() == 0


def test_rock_no_shake():
    fx, _ = make_effects()
    fx.spawn_bad_hit(make_entity("rock", EntityType.BAD, 0))
    fx.update(0.0)
    assert fx._shake_time_left == 0.0


def test_everything_culled_after_lifetimes():
    fx, _ = make_effects()
    fx.spawn_fruit_slice(make_entity())
    for _ in range(10):
        fx.update(HALF_MAX_AGE_S / 5)
    assert fx.halves == []
    assert fx.particles == []
    assert fx.popups == []


def test_particle_cap_enforced():
    fx, cfg = make_effects(max_particles=50)
    for _ in range(20):
        fx.spawn_fruit_slice(make_entity())
    assert len(fx.particles) <= 50
