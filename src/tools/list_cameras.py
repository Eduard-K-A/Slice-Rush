"""Camera discovery — run first on any new machine or after replugging USB.

Scans indices 0-5 on BOTH Windows backends (DirectShow and Media
Foundation): physical UVC webcams usually work best via dshow, while some
virtual cameras (DroidCam, phone-link cameras) only stream via msmf.
Reports which backend delivered frames so you can set both
camera.device_index and camera.backend in config/config.yaml.

Run: python -m src.tools.list_cameras
"""
from __future__ import annotations

import cv2

MAX_INDEX = 5
PREVIEW_SECONDS = 3
BACKENDS = [("dshow", cv2.CAP_DSHOW), ("msmf", cv2.CAP_MSMF)]


def _try_open(index: int, backend_flag: int):
    """Returns (cap, width, height, brightness) if the device delivers a
    real frame, else None."""
    cap = cv2.VideoCapture(index, backend_flag)
    if not cap.isOpened():
        cap.release()
        return None
    ok, frame = None, None
    for _ in range(15):
        ok, frame = cap.read()
        if ok and frame is not None:
            break
    if not ok or frame is None:
        cap.release()
        return None
    return cap, frame.shape[1], frame.shape[0], float(frame.mean())


def main() -> int:
    try:  # silence OpenCV's per-probe warning spam
        cv2.utils.logging.setLogLevel(cv2.utils.logging.LOG_LEVEL_ERROR)
    except AttributeError:
        pass

    found = []  # (index, backend_name, cap, w, h, brightness)
    print(f"Scanning camera indices 0..{MAX_INDEX} on dshow + msmf (each open can take a few seconds)…\n")
    for idx in range(MAX_INDEX + 1):
        for backend_name, flag in BACKENDS:
            result = _try_open(idx, flag)
            if result is not None:
                cap, w, h, brightness = result
                found.append((idx, backend_name, cap, w, h, brightness))
                break  # first working backend wins for this index

    print(f"{'index':<7}{'backend':<9}{'resolution':<14}{'brightness':<12}")
    for idx, backend_name, _, w, h, brightness in found:
        note = "  <- image is nearly black (lens cover? not streaming?)" if brightness < 20 else ""
        print(f"{idx:<7}{backend_name:<9}{f'{w}x{h}':<14}{brightness:<12.1f}{note}")
    if not found:
        print("No cameras delivered frames.")
        print(" - Physical cam: check USB cable and Windows camera privacy settings.")
        print(" - DroidCam/virtual cam: the client app must be running AND connected")
        print("   to the phone (video visible in the client window) before scanning.")
        return 1

    print(f"\nShowing each camera for {PREVIEW_SECONDS}s (press any key to skip ahead)…")
    for idx, backend_name, cap, _, _, _ in found:
        window = f"Camera {idx} ({backend_name}) — press any key for next"
        end = cv2.getTickCount() + PREVIEW_SECONDS * cv2.getTickFrequency()
        while cv2.getTickCount() < end:
            ok, frame = cap.read()
            if not ok:
                break
            cv2.putText(frame, f"index {idx} ({backend_name})", (30, 60), cv2.FONT_HERSHEY_SIMPLEX, 2, (0, 255, 0), 4)
            cv2.imshow(window, frame)
            if cv2.waitKey(15) >= 0:
                break
        cv2.destroyWindow(window)
        cap.release()

    print("\nIn config/config.yaml set BOTH:")
    print("  camera.device_index: <the index of the camera you want>")
    print("  camera.backend:      <its backend column above>")
    print("For virtual cameras (DroidCam etc.) also set camera.manual_exposure: false")
    print("and lock exposure/white-balance in the phone app instead.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
