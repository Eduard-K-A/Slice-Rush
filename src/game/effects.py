"""Slice feedback: flying fruit halves, juice particles, score popups,
screen shake, red flash. Every list here is bounded — a multi-hour booth
session must not grow memory in this module.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import List, Tuple

import numpy as np

from src.config_loader import EffectsConfig, PhysicsConfig
from src.game.entities import FallingEntity, EntityType

# Per-fruit juice colors (plan section 16.3).
JUICE_COLORS = {
    "apple": (200, 230, 120),
    "banana": (250, 235, 150),
    "strawberry": (230, 60, 90),
    "pineapple": (250, 220, 90),
    "watermelon": (235, 80, 100),
}
BOMB_SPARK_COLORS = [(255, 160, 40), (255, 220, 80)]
BOMB_SMOKE_COLOR = (120, 120, 120)
ROCK_CHIP_COLOR = (130, 130, 135)

HALF_MAX_AGE_S = 2.5
SHAKE_DURATION_S = 0.35
SHAKE_AMPLITUDE_PX = 10.0
RED_FLASH_DURATION_S = 0.25
RED_FLASH_PEAK_ALPHA = 120
POPUP_RISE_PX_S = 50.0
MAX_HALVES = 40
MAX_POPUPS = 20


@dataclass
class HalfEffect:
    sprite_key: str
    position: np.ndarray
    velocity: np.ndarray
    rotation_deg: float
    spin_deg_s: float
    age_s: float = 0.0


@dataclass
class JuiceParticle:
    position: np.ndarray
    velocity: np.ndarray
    color: Tuple[int, int, int]
    radius_px: float
    age_s: float = 0.0
    lifetime_s: float = 0.6


@dataclass
class ScorePopup:
    text: str
    position: np.ndarray
    color: Tuple[int, int, int]
    age_s: float = 0.0
    lifetime_s: float = 0.8


class EffectsSystem:
    def __init__(self, config: EffectsConfig, physics: PhysicsConfig, rng: random.Random | None = None):
        self._config = config
        self._physics = physics
        self._rng = rng or random.Random()
        self.halves: List[HalfEffect] = []
        self.particles: List[JuiceParticle] = []
        self.popups: List[ScorePopup] = []
        self._shake_time_left = 0.0
        self._red_flash_time_left = 0.0
        self._screen_height = 10_000  # renderer sets the real value once

    def set_screen_height(self, height: int) -> None:
        self._screen_height = height

    # ------------------------------------------------------------------ spawns

    def spawn_fruit_slice(self, entity: FallingEntity, combo: int = 0) -> None:
        rng = self._rng
        for i, key in enumerate((f"{entity.subtype}_half_1", f"{entity.subtype}_half_2")):
            kick = rng.uniform(80, 160) * (-1 if i == 0 else 1)
            spin = rng.uniform(90, 270) * (-1 if i == 0 else 1)
            self.halves.append(
                HalfEffect(
                    sprite_key=key,
                    position=entity.position.astype(np.float32).copy(),
                    velocity=entity.velocity.astype(np.float32) + np.array([kick, 0], dtype=np.float32),
                    rotation_deg=entity.rotation_deg,
                    spin_deg_s=spin,
                )
            )
        color = JUICE_COLORS.get(entity.subtype, (255, 255, 255))
        self._burst(entity.position, self._config.particles_per_slice, [color])
        self._splat(entity.position, 6, [color])
        text = f"+{entity.points}" if combo < 2 else f"+{entity.points} x{combo}!"
        self._popup(text, entity.position, (255, 255, 255))
        self._enforce_caps()

    def spawn_heart_restore(self, x: float, y: float) -> None:
        pos = np.array([x, y], dtype=np.float32)
        self._popup("+1 ♥", pos, (255, 80, 80))

    def spawn_bad_hit(self, entity: FallingEntity) -> None:
        n = self._config.particles_per_slice
        if entity.subtype == "bomb":
            self._burst(entity.position, n, BOMB_SPARK_COLORS, speed_max=520)
            self._burst(entity.position, n, [BOMB_SMOKE_COLOR], speed_max=250)
            self.trigger_screen_shake()
        else:
            self._burst(entity.position, n, [ROCK_CHIP_COLOR])
        self._popup("-1 ♥", entity.position, (230, 60, 60))
        self._red_flash_time_left = RED_FLASH_DURATION_S
        self._enforce_caps()

    def _burst(self, position: np.ndarray, count: int, colors, speed_max: float = 420.0) -> None:
        rng = self._rng
        for _ in range(count):
            angle = rng.uniform(0, 2 * np.pi)
            speed = rng.uniform(100, speed_max)
            self.particles.append(
                JuiceParticle(
                    position=position.astype(np.float32).copy(),
                    velocity=np.array([np.cos(angle), np.sin(angle)], dtype=np.float32) * speed,
                    color=rng.choice(colors) if len(colors) > 1 else colors[0],
                    radius_px=rng.uniform(3, 7),
                )
            )

    def _splat(self, position: np.ndarray, count: int, colors) -> None:
        """Large, slow-moving ink-blob particles that give a juice-splatter look."""
        rng = self._rng
        for _ in range(count):
            angle = rng.uniform(0, 2 * np.pi)
            speed = rng.uniform(15, 70)
            self.particles.append(
                JuiceParticle(
                    position=position.astype(np.float32).copy(),
                    velocity=np.array([np.cos(angle) * speed, np.sin(angle) * speed - 25], dtype=np.float32),
                    color=rng.choice(colors) if len(colors) > 1 else colors[0],
                    radius_px=rng.uniform(10, 22),
                    lifetime_s=rng.uniform(0.28, 0.48),
                )
            )

    def _popup(self, text: str, position: np.ndarray, color: Tuple[int, int, int]) -> None:
        self.popups.append(
            ScorePopup(
                text=text,
                position=position.astype(np.float32).copy(),
                color=color,
                lifetime_s=self._config.score_popup_seconds,
            )
        )

    # ------------------------------------------------------------------ shake / flash

    def trigger_screen_shake(self) -> None:
        if self._config.screen_shake_enabled:
            self._shake_time_left = SHAKE_DURATION_S

    def shake_offset(self) -> Tuple[int, int]:
        if self._shake_time_left <= 0:
            return (0, 0)
        amplitude = SHAKE_AMPLITUDE_PX * (self._shake_time_left / SHAKE_DURATION_S)
        return (
            int(self._rng.uniform(-amplitude, amplitude)),
            int(self._rng.uniform(-amplitude, amplitude)),
        )

    def red_flash_alpha(self) -> int:
        if self._red_flash_time_left <= 0:
            return 0
        return int(RED_FLASH_PEAK_ALPHA * (self._red_flash_time_left / RED_FLASH_DURATION_S))

    # ------------------------------------------------------------------ update

    def update(self, dt: float) -> None:
        gravity = self._physics.gravity_px_s2
        for h in self.halves:
            h.velocity[1] += gravity * dt
            h.position += h.velocity * dt
            h.rotation_deg = (h.rotation_deg + h.spin_deg_s * dt) % 360.0
            h.age_s += dt
        self.halves = [
            h for h in self.halves if h.age_s <= HALF_MAX_AGE_S and h.position[1] < self._screen_height + 200
        ]

        for p in self.particles:
            p.velocity[1] += gravity * dt
            p.position += p.velocity * dt
            p.age_s += dt
        self.particles = [p for p in self.particles if p.age_s < p.lifetime_s]

        for s in self.popups:
            s.position[1] -= POPUP_RISE_PX_S * dt
            s.age_s += dt
        self.popups = [s for s in self.popups if s.age_s < s.lifetime_s]

        self._shake_time_left = max(0.0, self._shake_time_left - dt)
        self._red_flash_time_left = max(0.0, self._red_flash_time_left - dt)

    def _enforce_caps(self) -> None:
        if len(self.particles) > self._config.max_particles:
            self.particles = self.particles[-self._config.max_particles:]
        if len(self.halves) > MAX_HALVES:
            self.halves = self.halves[-MAX_HALVES:]
        if len(self.popups) > MAX_POPUPS:
            self.popups = self.popups[-MAX_POPUPS:]
