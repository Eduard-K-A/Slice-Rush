"""Threaded camera capture for an external USB UVC camera on Windows.

The one background thread in the whole system (plan A11): it continuously
reads frames and publishes the newest one into a latest-frame slot under a
lock. The main/render loop polls `read_latest()` non-blockingly, so a
30 fps camera never caps the 60 fps render loop.

All frames are mirrored here (if configured) — every downstream consumer
works in mirrored coordinate space.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Optional, Tuple

import cv2
import numpy as np

from src.config_loader import CameraConfig

log = logging.getLogger(__name__)

_BACKENDS = {
    "dshow": cv2.CAP_DSHOW,
    "msmf": cv2.CAP_MSMF,
    "any": cv2.CAP_ANY,
}


class CameraCapture:
    def __init__(self, config: CameraConfig):
        self._config = config
        self._cap: Optional[cv2.VideoCapture] = None
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._frame: Optional[np.ndarray] = None
        self._frame_id = 0
        self._frame_time = 0.0
        self._consecutive_failures = 0
        self._last_reconnect_attempt = 0.0

    # ------------------------------------------------------------------ open

    def open(self) -> bool:
        backend = _BACKENDS.get(self._config.backend, cv2.CAP_ANY)
        cap = cv2.VideoCapture(self._config.device_index, backend)
        if not cap.isOpened():
            log.error(
                "camera %d failed to open (backend=%s)",
                self._config.device_index,
                self._config.backend,
            )
            return False

        # FOURCC before width/height matters on some drivers.
        self._set_and_log(cap, cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*self._config.fourcc), "FOURCC")
        self._set_and_log(cap, cv2.CAP_PROP_FRAME_WIDTH, self._config.frame_width, "FRAME_WIDTH")
        self._set_and_log(cap, cv2.CAP_PROP_FRAME_HEIGHT, self._config.frame_height, "FRAME_HEIGHT")
        self._set_and_log(cap, cv2.CAP_PROP_FPS, self._config.target_fps, "FPS")

        if self._config.manual_exposure:
            self._set_and_log(cap, cv2.CAP_PROP_AUTO_EXPOSURE, self._config.auto_exposure_off_value, "AUTO_EXPOSURE")
            self._set_and_log(cap, cv2.CAP_PROP_EXPOSURE, self._config.exposure_value, "EXPOSURE")
            self._set_and_log(cap, cv2.CAP_PROP_GAIN, self._config.gain, "GAIN")

        if self._config.disable_auto_white_balance:
            self._set_and_log(cap, cv2.CAP_PROP_AUTO_WB, 0, "AUTO_WB")
            if self._config.white_balance_temperature is not None:
                self._set_and_log(
                    cap, cv2.CAP_PROP_WB_TEMPERATURE, self._config.white_balance_temperature, "WB_TEMPERATURE"
                )

        self._cap = cap
        self._consecutive_failures = 0
        if self._thread is None or not self._thread.is_alive():
            self._stop.clear()
            self._thread = threading.Thread(target=self._capture_loop, daemon=True, name="camera-capture")
            self._thread.start()
        return True

    @staticmethod
    def _set_and_log(cap: cv2.VideoCapture, prop: int, value, name: str) -> None:
        cap.set(prop, value)
        actual = cap.get(prop)
        if abs(actual - float(value)) > 1e-3:
            log.warning("camera property %s: requested %s, driver reports %s", name, value, actual)
        else:
            log.info("camera property %s accepted: %s", name, actual)

    # ------------------------------------------------------------------ thread body

    def _capture_loop(self) -> None:
        while not self._stop.is_set():
            cap = self._cap
            if cap is None:
                time.sleep(0.05)
                continue
            try:
                ok, frame = cap.read()
            except cv2.error:
                ok, frame = False, None
            if ok and frame is not None:
                if self._config.mirror:
                    frame = cv2.flip(frame, 1)
                with self._lock:
                    self._frame = frame
                    self._frame_id += 1
                    self._frame_time = time.monotonic()
                    self._consecutive_failures = 0
            else:
                self._consecutive_failures += 1
                time.sleep(0.005)

    # ------------------------------------------------------------------ consumers

    def read_latest(self) -> Tuple[Optional[np.ndarray], int]:
        """Newest published frame and its id; (None, 0) before first frame.
        The returned array must be treated as read-only."""
        with self._lock:
            return self._frame, self._frame_id

    def seconds_since_last_frame(self) -> float:
        with self._lock:
            t = self._frame_time
        if t == 0.0:
            return float("inf")
        return time.monotonic() - t

    def is_healthy(self) -> bool:
        return self._consecutive_failures < self._config.reconnect_after_failures

    def maintain(self) -> None:
        """Called once per render frame. Handles the release+reopen cycle
        after a run of failed reads (e.g. USB cable knocked out)."""
        if self.is_healthy():
            return
        now = time.monotonic()
        if now - self._last_reconnect_attempt < self._config.reconnect_cooldown_seconds:
            return
        self._last_reconnect_attempt = now
        log.warning("camera unhealthy (%d consecutive failures) — attempting reconnect", self._consecutive_failures)
        try:
            if self._cap is not None:
                self._cap.release()
        except cv2.error:
            pass
        self._cap = None
        self.open()

    def release(self) -> None:
        self._stop.set()
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        if self._cap is not None:
            self._cap.release()
            self._cap = None
