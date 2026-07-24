"""Frozen-build entry point.

PyInstaller analyses from the repo root so the ``src`` package (and its
``from src....`` absolute imports) resolves. Run directly this is equivalent
to ``python -m src.main``.

Passing ``--calibrate`` runs the HSV/hand calibration tool instead of the
game. In a frozen build this is how the Settings screen relaunches the
calibrator (there is no ``python -m src.tools.calibrate`` to call).
"""
import sys

if __name__ == "__main__":
    if "--calibrate" in sys.argv[1:]:
        from src.tools.calibrate import main as calibrate_main
        raise SystemExit(calibrate_main())
    from src.main import main
    raise SystemExit(main())
