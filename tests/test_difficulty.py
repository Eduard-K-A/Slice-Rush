import pytest

from src.game.difficulty import bad_object_ratio, round_target, spawn_interval

BASE_TARGET, INC_TARGET = 40, 40
BASE_INT, DECAY, MIN_INT = 1.2, 0.08, 0.35
BASE_RATIO, INC_RATIO, MAX_RATIO = 0.15, 0.03, 0.5


# Table from plan section 8.8 — exact.
@pytest.mark.parametrize(
    "rnd,target,interval,ratio",
    [
        (1, 40, 1.20, 0.15),
        (2, 80, 1.12, 0.18),
        (3, 120, 1.04, 0.21),
        (4, 160, 0.96, 0.24),
    ],
)
def test_table_rounds_1_to_4(rnd, target, interval, ratio):
    assert round_target(rnd, BASE_TARGET, INC_TARGET) == target
    assert spawn_interval(rnd, BASE_INT, DECAY, MIN_INT) == pytest.approx(interval)
    assert bad_object_ratio(rnd, BASE_RATIO, INC_RATIO, MAX_RATIO) == pytest.approx(ratio)


def test_clamping_at_high_rounds():
    assert spawn_interval(20, BASE_INT, DECAY, MIN_INT) == pytest.approx(MIN_INT)
    assert bad_object_ratio(20, BASE_RATIO, INC_RATIO, MAX_RATIO) == pytest.approx(MAX_RATIO)
