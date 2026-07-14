import numpy as np
import pytest

from src.game.entities import EntityType, FallingEntity
from src.game.slice_logic import SliceTrail, resolve_slices, segment_intersects_circle


# The four reference cases from the plan, literally.
@pytest.mark.parametrize(
    "p1,p2,center,radius,expected",
    [
        ((0, 0), (100, 0), (50, 10), 15, True),
        ((0, 0), (100, 0), (50, 50), 15, False),
        ((0, 0), (10, 0), (20, 0), 5, False),  # clamps to endpoint (10,0), distance 10
        ((0, 0), (10, 0), (10, 0), 5, True),   # closest point is the endpoint, distance 0
    ],
)
def test_segment_circle_reference_cases(p1, p2, center, radius, expected):
    assert segment_intersects_circle(p1, p2, center, radius) is expected


def test_zero_length_segment():
    assert segment_intersects_circle((5, 5), (5, 5), (5, 8), 5) is True
    assert segment_intersects_circle((5, 5), (5, 5), (50, 50), 5) is False


def make_entity(eid, x, y, radius=40):
    return FallingEntity(
        id=eid,
        entity_type=EntityType.FRUIT,
        subtype="apple",
        position=np.array([x, y], dtype=np.float32),
        velocity=np.zeros(2, dtype=np.float32),
        radius_px=radius,
        points=10,
        rotation_deg=0.0,
        spin_deg_s=0.0,
    )


def test_resolve_slices_marks_only_intersecting():
    hit = make_entity(1, 50, 10)
    miss = make_entity(2, 50, 300)
    hits = resolve_slices(((0, 0), (100, 0)), [hit, miss])
    assert hits == [hit]
    assert hit.sliced and not miss.sliced


def test_resolve_slices_skips_already_sliced():
    e = make_entity(1, 50, 10)
    e.sliced = True
    assert resolve_slices(((0, 0), (100, 0)), [e]) == []


def test_trail_bounded_and_segment():
    trail = SliceTrail(max_points=3)
    assert trail.get_last_segment() is None
    for i in range(10):
        trail.add_point((i, i * 2))
    assert len(trail.points()) == 3
    seg = trail.get_last_segment()
    assert seg == ((8.0, 16.0), (9.0, 18.0))
    trail.clear()
    assert trail.get_last_segment() is None
