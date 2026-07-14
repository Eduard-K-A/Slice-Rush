"""Authoritative difficulty formulas (plan section 8.8 — do not approximate).

With default config these produce the PRD's target sequence 40, 80, 120,
160, ... which is the correctness check for round_target.
"""
from __future__ import annotations


def round_target(round_number: int, base: int, increment: int) -> int:
    return base + increment * (round_number - 1)


def spawn_interval(round_number: int, base: float, decay: float, minimum: float) -> float:
    return max(minimum, base - decay * (round_number - 1))


def bad_object_ratio(round_number: int, base: float, increment: float, maximum: float) -> float:
    return min(maximum, base + increment * (round_number - 1))
