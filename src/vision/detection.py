"""HSV color-blob detection of the LED marker(s).

Strategy pattern: `MarkerDetector` is the interface; `ColorBlobDetector`
is the v1 implementation. A future ArUco/IR detector can be swapped in
without touching tracking, slice logic, or main.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional, Protocol, Tuple

import cv2
import numpy as np

from src.config_loader import DetectionConfig


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
