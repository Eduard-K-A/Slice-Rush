"""Interactive HSV + exposure calibration.

Run on-site before the booth opens and re-run whenever lighting changes.
Uses the same CameraCapture + blur/morphology as the game, so what you
see in the mask window is exactly what the game will see.

Run: python -m src.tools.calibrate

Keys:
  t  edit the 'tip' marker      h  edit the 'handle' marker (if configured)
  e  cycle exposure presets (-5, -7, -9)
  d  open the DirectShow driver settings dialog (manual exposure/WB lock)
  s  save the edited marker's HSV bounds + current exposure to config.yaml
  q  quit without saving
"""
from __future__ import annotations

import logging

import cv2
import numpy as np
import yaml

from src.config_loader import load_config
from src.vision.capture import CameraCapture

CONFIG_PATH = "config/config.yaml"
EXPOSURE_PRESETS = [-5, -7, -9]

TRACKBARS = [
    ("H min", 179), ("H max", 179),
    ("S min", 255), ("S max", 255),
    ("V min", 255), ("V max", 255),
]


def _set_trackbars(lower, upper) -> None:
    cv2.setTrackbarPos("H min", "controls", lower[0])
    cv2.setTrackbarPos("H max", "controls", upper[0])
    cv2.setTrackbarPos("S min", "controls", lower[1])
    cv2.setTrackbarPos("S max", "controls", upper[1])
    cv2.setTrackbarPos("V min", "controls", lower[2])
    cv2.setTrackbarPos("V max", "controls", upper[2])


def _get_bounds() -> tuple[list[int], list[int]]:
    lower = [
        cv2.getTrackbarPos("H min", "controls"),
        cv2.getTrackbarPos("S min", "controls"),
        cv2.getTrackbarPos("V min", "controls"),
    ]
    upper = [
        cv2.getTrackbarPos("H max", "controls"),
        cv2.getTrackbarPos("S max", "controls"),
        cv2.getTrackbarPos("V max", "controls"),
    ]
    return lower, upper


def _save(marker_name: str, lower: list[int], upper: list[int], exposure: float) -> None:
    with open(CONFIG_PATH, "r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)
    for marker in raw["detection"]["markers"]:
        if marker["name"] == marker_name:
            marker["hsv_lower"] = lower
            marker["hsv_upper"] = upper
    raw["camera"]["exposure_value"] = exposure
    with open(CONFIG_PATH, "w", encoding="utf-8") as fh:
        yaml.safe_dump(raw, fh, default_flow_style=False, sort_keys=False)
    print(f"\nSaved to {CONFIG_PATH}:")
    print(yaml.safe_dump(
        {"marker": marker_name, "hsv_lower": lower, "hsv_upper": upper, "exposure_value": exposure},
        default_flow_style=False, sort_keys=False,
    ))


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    print(__doc__)
    config = load_config(CONFIG_PATH)
    capture = CameraCapture(config.camera)
    if not capture.open():
        print("Camera failed to open — run: python -m src.tools.list_cameras")
        return 1

    markers = {m.name: m for m in config.detection.markers}
    current = "tip"
    exposure = float(config.camera.exposure_value)
    exposure_idx = EXPOSURE_PRESETS.index(exposure) if exposure in EXPOSURE_PRESETS else 1

    cv2.namedWindow("controls", cv2.WINDOW_NORMAL)
    for name, maximum in TRACKBARS:
        cv2.createTrackbar(name, "controls", 0, maximum, lambda _v: None)
    _set_trackbars(list(markers[current].hsv_lower), list(markers[current].hsv_upper))

    k = config.detection.blur_kernel
    open_kernel = cv2.getStructuringElement(
        cv2.MORPH_ELLIPSE, (config.detection.morphology.open_kernel,) * 2
    )
    close_kernel = cv2.getStructuringElement(
        cv2.MORPH_ELLIPSE, (config.detection.morphology.close_kernel,) * 2
    )

    last_id = 0
    while True:
        capture.maintain()
        frame, frame_id = capture.read_latest()
        if frame is not None and frame_id != last_id:
            last_id = frame_id
            lower, upper = _get_bounds()
            blurred = cv2.GaussianBlur(frame, (k, k), 0)
            hsv = cv2.cvtColor(blurred, cv2.COLOR_BGR2HSV)
            mask = cv2.inRange(hsv, np.array(lower), np.array(upper))
            mask = cv2.morphologyEx(
                mask, cv2.MORPH_OPEN, open_kernel, iterations=config.detection.morphology.open_iterations
            )
            mask = cv2.morphologyEx(
                mask, cv2.MORPH_CLOSE, close_kernel, iterations=config.detection.morphology.close_iterations
            )
            display = frame.copy()
            cv2.putText(
                display, f"editing: {current}   exposure: {exposure}", (20, 40),
                cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2,
            )
            cv2.imshow("camera", display)
            cv2.imshow("mask", mask)

        key = cv2.waitKey(5) & 0xFF
        if key == ord("q"):
            break
        elif key == ord("t"):
            current = "tip"
            _set_trackbars(list(markers["tip"].hsv_lower), list(markers["tip"].hsv_upper))
        elif key == ord("h"):
            if "handle" in markers:
                current = "handle"
                _set_trackbars(list(markers["handle"].hsv_lower), list(markers["handle"].hsv_upper))
            else:
                print("No 'handle' marker configured — add one to detection.markers to tune it.")
        elif key == ord("e"):
            exposure_idx = (exposure_idx + 1) % len(EXPOSURE_PRESETS)
            exposure = float(EXPOSURE_PRESETS[exposure_idx])
            if capture._cap is not None:
                capture._cap.set(cv2.CAP_PROP_EXPOSURE, exposure)
            print(f"exposure -> {exposure}")
        elif key == ord("d"):
            if capture._cap is not None and config.camera.backend == "dshow":
                capture._cap.set(cv2.CAP_PROP_SETTINGS, 1)
            else:
                print("Driver settings dialog is only available with the DirectShow backend (camera.backend: dshow).")
        elif key == ord("s"):
            lower, upper = _get_bounds()
            _save(current, lower, upper, exposure)

    capture.release()
    cv2.destroyAllWindows()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
