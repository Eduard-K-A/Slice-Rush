"""Tip trail buffer + segment-vs-circle slice collision.

The collision segment is always the last two smoothed TIP points, added
once per new camera frame. The slice speed gate is applied by the caller
(main.py) — `resolve_slices` stays purely geometric and testable.
"""
from __future__ import annotations

from collections import deque
from typing import List, Optional, Tuple

import numpy as np

from src.game.entities import FallingEntity

Point = Tuple[float, float]


class SliceTrail:
    def __init__(self, max_points: int):
        self._points: deque[Point] = deque(maxlen=max_points)

    def add_point(self, point: Point) -> None:
        self._points.append((float(point[0]), float(point[1])))

    def get_last_segment(self) -> Optional[Tuple[Point, Point]]:
        if len(self._points) < 2:
            return None
        return (self._points[-2], self._points[-1])

    def points(self) -> List[Point]:
        return list(self._points)

    def clear(self) -> None:
        self._points.clear()


def segment_intersects_circle(p1: Point, p2: Point, center: Point, radius: float) -> bool:
    p1 = np.array(p1, dtype=float)
    p2 = np.array(p2, dtype=float)
    c = np.array(center, dtype=float)
    d = p2 - p1
    length_sq = float(np.dot(d, d))
    if length_sq == 0.0:
        return float(np.linalg.norm(p1 - c)) <= radius
    t = max(0.0, min(1.0, float(np.dot(c - p1, d) / length_sq)))
    closest = p1 + t * d
    return float(np.linalg.norm(closest - c)) <= radius


def resolve_slices(segment: Tuple[Point, Point], entities: List[FallingEntity]) -> List[FallingEntity]:
    """Subset of not-yet-sliced entities whose hit circle intersects the
    segment; marks each returned entity sliced=True as a side effect."""
    p1, p2 = segment
    hits: List[FallingEntity] = []
    for e in entities:
        if e.sliced:
            continue
        if segment_intersects_circle(p1, p2, (float(e.position[0]), float(e.position[1])), e.radius_px):
            e.sliced = True
            hits.append(e)
    return hits
