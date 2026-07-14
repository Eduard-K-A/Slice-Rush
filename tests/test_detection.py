import cv2
import numpy as np

from src.config_loader import DetectionConfig, MarkerConfig, MorphologyConfig
from src.vision.detection import ColorBlobDetector


def make_config(markers):
    return DetectionConfig(
        markers=markers,
        blur_kernel=5,
        morphology=MorphologyConfig(open_kernel=3, open_iterations=1, close_kernel=5, close_iterations=2),
    )


TIP = MarkerConfig(
    name="tip",
    hsv_lower=(50, 100, 100),
    hsv_upper=(70, 255, 255),
    min_area_px=15,
    max_area_px=10000,
)


def green_frame_with_circle(center, radius=20):
    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    cv2.circle(frame, center, radius, (0, 255, 0), -1)  # pure green: HSV hue 60
    return frame


def test_detects_circle_center_within_3px():
    detector = ColorBlobDetector(make_config([TIP]))
    result = detector.detect(green_frame_with_circle((320, 240)))
    det = result["tip"]
    assert det.found
    assert abs(det.center[0] - 320) <= 3
    assert abs(det.center[1] - 240) <= 3


def test_empty_frame_not_found():
    detector = ColorBlobDetector(make_config([TIP]))
    result = detector.detect(np.zeros((480, 640, 3), dtype=np.uint8))
    det = result["tip"]
    assert not det.found
    assert det.center is None


def test_largest_of_two_blobs_wins():
    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    cv2.circle(frame, (100, 100), 10, (0, 255, 0), -1)
    cv2.circle(frame, (500, 400), 30, (0, 255, 0), -1)
    detector = ColorBlobDetector(make_config([TIP]))
    det = detector.detect(frame)["tip"]
    assert det.found
    assert abs(det.center[0] - 500) <= 3
    assert abs(det.center[1] - 400) <= 3


def test_area_filter_rejects_too_small():
    frame = green_frame_with_circle((320, 240), radius=2)
    detector = ColorBlobDetector(make_config([TIP]))
    det = detector.detect(frame)["tip"]
    assert not det.found
