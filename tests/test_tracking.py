import numpy as np

from src.config_loader import KalmanConfig
from src.vision.tracking import MarkerTracker

CFG = KalmanConfig(process_noise=1e-2, measurement_noise=1e-1, max_missed_frames=8)
DT = 1.0 / 30


def test_smoothing_reduces_rms_error():
    rng = np.random.default_rng(42)
    tracker = MarkerTracker(CFG, DT)
    n = 200
    truth = np.stack([100 + 5 * np.arange(n), 200 + 3 * np.arange(n)], axis=1).astype(float)
    noisy = truth + rng.normal(0, 8, truth.shape)
    smoothed = np.array([tracker.update((x, y)) for x, y in noisy])
    # skip the convergence window
    raw_rms = np.sqrt(np.mean((noisy[50:] - truth[50:]) ** 2))
    smooth_rms = np.sqrt(np.mean((smoothed[50:] - truth[50:]) ** 2))
    assert smooth_rms < raw_rms


def test_dropout_predicts_and_flags_lost():
    tracker = MarkerTracker(CFG, DT)
    for i in range(30):
        tracker.update((100 + i * 2.0, 200.0))
    assert not tracker.is_lost()
    last = None
    for _ in range(CFG.max_missed_frames + 1):
        last = tracker.update(None)
    assert tracker.is_lost()
    assert np.isfinite(last).all()
    # prediction should continue rightward motion
    assert last[0] > 100


def test_reacquisition_resets_lost():
    tracker = MarkerTracker(CFG, DT)
    tracker.update((10, 10))
    for _ in range(CFG.max_missed_frames + 2):
        tracker.update(None)
    assert tracker.is_lost()
    tracker.update((50, 50))
    assert not tracker.is_lost()


def test_speed_estimate_approximates_truth():
    tracker = MarkerTracker(CFG, DT)
    # 6 px per frame at 30fps = 180 px/s along x
    for i in range(120):
        tracker.update((i * 6.0, 100.0))
    assert abs(tracker.speed_px_s() - 180) / 180 < 0.25


def test_update_before_any_measurement_is_safe():
    tracker = MarkerTracker(CFG, DT)
    out = tracker.update(None)
    assert out == (0.0, 0.0)
