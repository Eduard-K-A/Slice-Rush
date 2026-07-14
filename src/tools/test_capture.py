"""Manual smoke test of the capture pipeline on real hardware.

Shows the live mirrored feed with measured fps + frame id overlaid, and
prints which camera properties the driver actually accepted (see the
log lines emitted by CameraCapture.open()).

Run: python -m src.tools.test_capture     (press q to quit)
"""
from __future__ import annotations

import logging
import time

import cv2

from src.config_loader import load_config
from src.vision.capture import CameraCapture


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    config = load_config("config/config.yaml")
    capture = CameraCapture(config.camera)
    if not capture.open():
        print("Camera failed to open — run: python -m src.tools.list_cameras")
        return 1

    last_id = 0
    frame_times: list[float] = []
    print("Live preview — press q to quit.")
    while True:
        capture.maintain()
        frame, frame_id = capture.read_latest()
        if frame is not None and frame_id != last_id:
            last_id = frame_id
            now = time.monotonic()
            frame_times.append(now)
            frame_times = [t for t in frame_times if now - t < 2.0]
            fps = len(frame_times) / 2.0
            display = frame.copy()
            cv2.putText(
                display,
                f"fps {fps:.1f}  frame {frame_id}  (mirrored={config.camera.mirror})",
                (20, 40),
                cv2.FONT_HERSHEY_SIMPLEX,
                1,
                (0, 255, 0),
                2,
            )
            cv2.imshow("test_capture — q quits", display)
        if cv2.waitKey(5) & 0xFF == ord("q"):
            break

    capture.release()
    cv2.destroyAllWindows()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
