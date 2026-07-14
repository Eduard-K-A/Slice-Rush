"""Falling entities (fruit / bad objects): value objects + spawn/physics."""
from __future__ import annotations

import random
from dataclasses import dataclass
from enum import Enum
from typing import List

import numpy as np

from src.config_loader import AssetsConfig, GameConfig
from src.game.difficulty import bad_object_ratio


class EntityType(Enum):
    FRUIT = "fruit"
    BAD = "bad"


@dataclass
class FallingEntity:
    id: int
    entity_type: EntityType
    subtype: str
    position: np.ndarray  # shape (2,) float32, sprite center in screen px
    velocity: np.ndarray  # shape (2,) float32, px/s
    radius_px: int
    points: int
    rotation_deg: float
    spin_deg_s: float
    sliced: bool = False
    missed: bool = False


class EntitySpawner:
    def __init__(
        self,
        config: GameConfig,
        assets: AssetsConfig,
        screen_width: int,
        screen_height: int,
        rng: random.Random | None = None,
    ):
        self._config = config
        self._radius = assets.entity_sprite_px // 2
        self._width = screen_width
        self._height = screen_height
        self._rng = rng or random.Random()

    def spawn(self, round_number: int, next_id: int, fruit_only: bool = False) -> FallingEntity:
        cfg = self._config
        ratio = bad_object_ratio(
            round_number,
            cfg.difficulty.base_bad_object_ratio,
            cfg.difficulty.bad_object_ratio_increment_per_round,
            cfg.difficulty.max_bad_object_ratio,
        )
        is_bad = (not fruit_only) and self._rng.random() < ratio
        if is_bad:
            subtype = self._rng.choice(cfg.scoring.bad_object_types)
            entity_type, points = EntityType.BAD, 0
        else:
            subtype = self._rng.choice(list(cfg.scoring.fruit_points.keys()))
            entity_type, points = EntityType.FRUIT, cfg.scoring.fruit_points[subtype]

        r = self._radius
        phys = cfg.physics
        x = self._rng.uniform(2 * r, self._width - 2 * r)
        vy = self._rng.uniform(phys.fall_speed_min_px_s, phys.fall_speed_max_px_s)
        vx = self._rng.uniform(-phys.horizontal_speed_max_px_s, phys.horizontal_speed_max_px_s)
        return FallingEntity(
            id=next_id,
            entity_type=entity_type,
            subtype=subtype,
            position=np.array([x, -r], dtype=np.float32),
            velocity=np.array([vx, vy], dtype=np.float32),
            radius_px=r,
            points=points,
            rotation_deg=self._rng.uniform(0.0, 360.0),
            spin_deg_s=self._rng.uniform(-phys.spin_max_deg_s, phys.spin_max_deg_s),
        )

    def update(self, entities: List[FallingEntity], dt: float) -> None:
        gravity = self._config.physics.gravity_px_s2
        for e in entities:
            e.velocity[1] += gravity * dt
            e.position += e.velocity * dt
            e.rotation_deg = (e.rotation_deg + e.spin_deg_s * dt) % 360.0
            if (
                e.entity_type is EntityType.FRUIT
                and not e.sliced
                and not e.missed
                and e.position[1] - e.radius_px > self._height
            ):
                e.missed = True

    def is_off_screen(self, entity: FallingEntity) -> bool:
        return entity.position[1] - entity.radius_px > self._height
