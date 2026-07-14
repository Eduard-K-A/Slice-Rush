import random

import numpy as np

from src.config_loader import AssetsConfig, GameConfig
from src.game.entities import EntitySpawner, EntityType

W, H = 1280, 720


def make_spawner(seed=123):
    return EntitySpawner(GameConfig(), AssetsConfig(), W, H, random.Random(seed))


def test_spawn_within_bounds_and_ranges():
    spawner = make_spawner()
    cfg = GameConfig()
    r = AssetsConfig().entity_sprite_px // 2
    for i in range(500):
        e = spawner.spawn(1, i)
        assert 2 * r <= e.position[0] <= W - 2 * r
        assert e.position[1] == -r
        assert cfg.physics.fall_speed_min_px_s <= e.velocity[1] <= cfg.physics.fall_speed_max_px_s
        assert abs(e.velocity[0]) <= cfg.physics.horizontal_speed_max_px_s
        assert abs(e.spin_deg_s) <= cfg.physics.spin_max_deg_s
        assert e.radius_px == r
        if e.entity_type is EntityType.FRUIT:
            assert e.points == cfg.scoring.fruit_points[e.subtype]
        else:
            assert e.points == 0
            assert e.subtype in cfg.scoring.bad_object_types


def test_bad_ratio_approximates_config():
    spawner = make_spawner(7)
    n = 2000
    bad = sum(1 for i in range(n) if spawner.spawn(1, i).entity_type is EntityType.BAD)
    assert abs(bad / n - 0.15) < 0.04  # round 1 ratio 0.15


def test_fruit_only_flag():
    spawner = make_spawner(7)
    assert all(spawner.spawn(10, i, fruit_only=True).entity_type is EntityType.FRUIT for i in range(200))


def test_update_applies_gravity_and_marks_missed():
    spawner = make_spawner()
    e = spawner.spawn(1, 1, fruit_only=True)  # misses only apply to fruit
    vy0 = float(e.velocity[1])
    spawner.update([e], 0.1)
    assert float(e.velocity[1]) > vy0
    # teleport below screen
    e.position[1] = H + e.radius_px + 1
    spawner.update([e], 0.001)
    assert e.missed


def test_sliced_entity_not_marked_missed():
    spawner = make_spawner()
    e = spawner.spawn(1, 1)
    e.sliced = True
    e.position[1] = H + e.radius_px + 100
    spawner.update([e], 0.001)
    assert not e.missed
