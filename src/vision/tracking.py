"""Constant-velocity Kalman tracking of marker positions.

Plain-NumPy implementation (plan A12 — no filterpy dependency). One
`MarkerTracker` per configured marker, persisted across frames. Predicts
through short detection dropouts so the trail doesn't visually jump.
"""
from __future__ import annotations

import math
from typing import Optional, Tuple

import numpy as np

from src.config_loader import KalmanConfig


class Kalman2D:
    """Constant-velocity Kalman filter, dim_x=4 ([x, y, vx, vy]), dim_z=2."""

    def __init__(self, dt: float, process_noise: float, measurement_noise: float):
        self.x = np.zeros((4, 1))
        self.P = np.eye(4) * 500.0
        self.F = np.array(
            [[1, 0, dt, 0],
             [0, 1, 0, dt],
             [0, 0, 1, 0],
             [0, 0, 0, 1]],
            dtype=float,
        )
        self.H = np.array(
            [[1, 0, 0, 0],
             [0, 1, 0, 0]],
            dtype=float,
        )
        self.Q = np.eye(4) * process_noise
        self.R = np.eye(2) * measurement_noise
        self.initialized = False

    def predict(self) -> Tuple[float, float]:
        self.x = self.F @ self.x
        self.P = self.F @ self.P @ self.F.T + self.Q
        return float(self.x[0, 0]), float(self.x[1, 0])

    def update(self, z_x: float, z_y: float) -> Tuple[float, float]:
        if not self.initialized:
            self.x[0, 0], self.x[1, 0] = z_x, z_y
            self.initialized = True
            return z_x, z_y
        z = np.array([[z_x], [z_y]])
        y = z - self.H @ self.x
        S = self.H @ self.P @ self.H.T + self.R
        K = self.P @ self.H.T @ np.linalg.inv(S)
        self.x = self.x + K @ y
        self.P = (np.eye(4) - K @ self.H) @ self.P
        return float(self.x[0, 0]), float(self.x[1, 0])


class MarkerTracker:
    def __init__(self, config: KalmanConfig, dt: float):
        self._config = config
        self._kf = Kalman2D(dt, config.process_noise, config.measurement_noise)
        self._missed_frames = 0

    def update(self, measurement: Optional[Tuple[float, float]]) -> Tuple[float, float]:
        """Measurement present: predict then correct; missed counter resets.
        Measurement None: predict only; returns the prediction anyway so
        the trail stays continuous — callers check is_lost() before using
        the point for slicing."""
        if measurement is not None:
            if self._kf.initialized:
                self._kf.predict()
            smoothed = self._kf.update(measurement[0], measurement[1])
            self._missed_frames = 0
            return smoothed
        self._missed_frames += 1
        if not self._kf.initialized:
            return (0.0, 0.0)
        return self._kf.predict()

    def is_lost(self) -> bool:
        return self._missed_frames > self._config.max_missed_frames

    def speed_px_s(self) -> float:
        """Magnitude of the Kalman velocity state — used by the slice-speed gate."""
        vx = float(self._kf.x[2, 0])
        vy = float(self._kf.x[3, 0])
        return math.hypot(vx, vy)
