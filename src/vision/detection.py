"""HSV color-blob detection of the LED marker(s).

Strategy pattern: `MarkerDetector` is the interface; `ColorBlobDetector`
is the v1 implementation. A future ArUco/IR detector can be swapped in
without touching tracking, slice logic, or main.
"""
from __future__ import annotations

import os
import time
import urllib.request
from dataclasses import dataclass
from typing import Dict, Optional, Protocol, Tuple

import cv2
import numpy as np

from src.config_loader import DetectionConfig, HandDetectionConfig


@dataclass
class MarkerDetection:
    name: str
    center: Optional[Tuple[float, float]]
    area: float
    found: bool


class MarkerDetector(Protocol):
    def detect(self, frame_bgr: np.ndarray) -> Dict[str, MarkerDetection]: ...


def _centroid(contour) -> Optional[Tuple[float, float]]:
    m = cv2.moments(contour)
    if m["m00"] == 0:
        return None
    return (m["m10"] / m["m00"], m["m01"] / m["m00"])


class ColorBlobDetector:
    def __init__(self, config: DetectionConfig):
        self._config = config
        self._open_kernel = cv2.getStructuringElement(
            cv2.MORPH_ELLIPSE, (config.morphology.open_kernel, config.morphology.open_kernel)
        )
        self._close_kernel = cv2.getStructuringElement(
            cv2.MORPH_ELLIPSE, (config.morphology.close_kernel, config.morphology.close_kernel)
        )
        self._last_masks: Dict[str, np.ndarray] = {}

    def detect(self, frame_bgr: np.ndarray) -> Dict[str, MarkerDetection]:
        k = self._config.blur_kernel
        blurred = cv2.GaussianBlur(frame_bgr, (k, k), 0)
        hsv = cv2.cvtColor(blurred, cv2.COLOR_BGR2HSV)
        results: Dict[str, MarkerDetection] = {}
        for marker in self._config.markers:
            mask = cv2.inRange(hsv, np.array(marker.hsv_lower), np.array(marker.hsv_upper))
            mask = cv2.morphologyEx(
                mask, cv2.MORPH_OPEN, self._open_kernel, iterations=self._config.morphology.open_iterations
            )
            mask = cv2.morphologyEx(
                mask, cv2.MORPH_CLOSE, self._close_kernel, iterations=self._config.morphology.close_iterations
            )
            self._last_masks[marker.name] = mask
            contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            best = None
            best_area = 0.0
            for c in contours:
                area = cv2.contourArea(c)
                if marker.min_area_px <= area <= marker.max_area_px and area > best_area:
                    best, best_area = c, area
            center = _centroid(best) if best is not None else None
            results[marker.name] = MarkerDetection(
                name=marker.name,
                center=center,
                area=best_area if center is not None else 0.0,
                found=center is not None,
            )
        return results

    def get_last_mask(self, name: str) -> Optional[np.ndarray]:
        """Most recent binary mask for a marker — debug overlay / calibrate."""
        return self._last_masks.get(name)


class HandDetector:
    """MediaPipe Hands detector implementing the MarkerDetector protocol.

    Tracks a single hand landmark (default: index fingertip, landmark 8) as
    the 'tip' marker. No color calibration required — works under any lighting.
    """

    # MediaPipe 21-landmark hand connections for drawing the skeleton
    _HAND_CONNECTIONS = [
        (0,1),(1,2),(2,3),(3,4),
        (0,5),(5,6),(6,7),(7,8),
        (0,9),(9,10),(10,11),(11,12),
        (0,13),(13,14),(14,15),(15,16),
        (0,17),(17,18),(18,19),(19,20),
        (5,9),(9,13),(13,17),
    ]
    _MODEL_URL = (
        "https://storage.googleapis.com/mediapipe-models/"
        "hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task"
    )

    def __init__(self, config: HandDetectionConfig) -> None:
        import mediapipe as mp  # imported here so missing mediapipe only fails when hand mode is active

        if not os.path.exists(config.model_path):
            os.makedirs(os.path.dirname(config.model_path) or ".", exist_ok=True)
            print(f"Downloading hand landmarker model to {config.model_path!r} (~9 MB) ...")
            urllib.request.urlretrieve(self._MODEL_URL, config.model_path)
            print("Download complete.")

        options = mp.tasks.vision.HandLandmarkerOptions(
            base_options=mp.tasks.BaseOptions(model_asset_path=config.model_path),
            running_mode=mp.tasks.vision.RunningMode.VIDEO,
            num_hands=config.max_num_hands,
            min_hand_detection_confidence=config.min_detection_confidence,
            min_tracking_confidence=config.min_tracking_confidence,
        )
        self._detector = mp.tasks.vision.HandLandmarker.create_from_options(options)
        self._mp = mp
        self._landmark_index = config.landmark_index
        self._last_overlay: Optional[np.ndarray] = None
        self._last_ts_ms: int = 0  # detect_for_video requires strictly increasing timestamps

    def detect(self, frame_bgr: np.ndarray) -> Dict[str, MarkerDetection]:
        not_found = {"tip": MarkerDetection(name="tip", center=None, area=0.0, found=False)}

        frame_rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        mp_image = self._mp.Image(image_format=self._mp.ImageFormat.SRGB, data=frame_rgb)
        ts_ms = max(int(time.monotonic() * 1000), self._last_ts_ms + 1)
        self._last_ts_ms = ts_ms
        result = self._detector.detect_for_video(mp_image, ts_ms)

        if not result.hand_landmarks:
            self._last_overlay = None
            return not_found

        landmarks = result.hand_landmarks[0]
        h, w = frame_bgr.shape[:2]
        lm = landmarks[self._landmark_index]
        cx, cy = lm.x * w, lm.y * h

        overlay = frame_bgr.copy()
        for a, b in self._HAND_CONNECTIONS:
            ax, ay = int(landmarks[a].x * w), int(landmarks[a].y * h)
            bx, by = int(landmarks[b].x * w), int(landmarks[b].y * h)
            cv2.line(overlay, (ax, ay), (bx, by), (180, 180, 180), 2)
        for lmk in landmarks:
            cv2.circle(overlay, (int(lmk.x * w), int(lmk.y * h)), 4, (200, 200, 200), -1)
        # Highlight the active tracking point (index fingertip) prominently
        cv2.circle(overlay, (int(cx), int(cy)), 14, (0, 80, 255), -1)   # orange fill
        cv2.circle(overlay, (int(cx), int(cy)), 14, (255, 255, 255), 2)  # white border
        self._last_overlay = overlay

        return {"tip": MarkerDetection(name="tip", center=(cx, cy), area=500.0, found=True)}

    def get_last_overlay(self) -> Optional[np.ndarray]:
        """BGR frame with hand skeleton drawn — used by calibrate and debug overlay."""
        return self._last_overlay
