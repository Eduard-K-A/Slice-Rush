"""Slice Rush orchestration — main.py wires modules together and contains
no detection or game-rule logic itself.

Run: python -m src.main
Volunteer keys: SPACE start · R abort to idle · F1 debug overlay · ESC quit.
"""
from __future__ import annotations

import logging
import os
import random
import subprocess
import sys
import time

# Booth robustness: SDL minimizes fullscreen windows on focus loss by
# default, which makes the game "vanish" when launched from a terminal.
os.environ.setdefault("SDL_VIDEO_MINIMIZE_ON_FOCUS_LOSS", "0")

import cv2
import numpy as np
import pygame

from src.config_loader import (
    AppConfig, DetectionConfig, HandDetectionConfig, MarkerConfig, MorphologyConfig,
    load_config, save_config,
)
from src.game.audio import AudioPlayer
from src.game.difficulty import spawn_interval
from src.game.effects import EffectsSystem
from src.game.entities import EntitySpawner, EntityType, FallingEntity
from src.game.game_state import GamePhase, GameStateMachine
from src.game.renderer import Renderer
from src.game.slice_logic import SliceTrail, resolve_slices
from src.persistence.leaderboard import Leaderboard
from src.vision.capture import CameraCapture
from src.vision.detection import ColorBlobDetector, HandDetector
from src.vision.tracking import MarkerTracker

log = logging.getLogger("slice_rush")

ATTRACT_SPAWN_INTERVAL_S = 1.5
CAMERA_STALE_AFTER_S = 1.0

_SETTINGS_ITEMS = ["Camera Index", "Detection Mode", "Color Preset", "Window Mode", "Fine-tune Calibration", "Back"]
_SETTINGS_CAMERA, _SETTINGS_MODE, _SETTINGS_PRESET, _SETTINGS_WINDOW, _SETTINGS_CALIBRATE, _SETTINGS_BACK = range(6)

# Red is simplified (one range); users needing precise dual-range red should use Fine-tune
_COLOR_PRESETS = [
    ("White/Bright",  [0,   0,   200], [179, 50,  255]),
    ("Neon Green",    [35,  100, 100], [85,  255, 255]),
    ("Bright Yellow", [22,  160, 160], [38,  255, 255]),
    ("Pink/Magenta",  [140, 100, 100], [170, 255, 255]),
    ("Blue",          [100, 100, 100], [130, 255, 255]),
    ("Red",           [0,   120, 100], [10,  255, 255]),
]


def _probe_cameras() -> list:
    """Blocking scan of indices 0-5 on dshow+msmf. Call once and cache."""
    results = []
    for idx in range(6):
        found, label = False, f"{idx}: not found"
        for bname, flag in [("dshow", cv2.CAP_DSHOW), ("msmf", cv2.CAP_MSMF)]:
            cap = cv2.VideoCapture(idx, flag)
            if not cap.isOpened():
                cap.release()
                continue
            frame = None
            for _ in range(15):
                ok, f = cap.read()
                if ok and f is not None:
                    frame = f
                    break
            cap.release()
            if frame is not None:
                h, w = frame.shape[:2]
                label = f"{idx}: {w}x{h} ({bname})"
                found = True
                break
        results.append((idx, found, label))
    return results


def _draw_settings_screen(
    screen: pygame.Surface,
    renderer,
    settings_cursor: int,
    cam_index: int,
    cam_probe_cache: list,
    detect_mode: str,
    preset_idx: int,
    fullscreen: bool,
) -> None:
    sw, sh = screen.get_size()
    screen.fill((12, 12, 18))

    title = renderer._font_banner.render("SETTINGS", True, (220, 220, 255))
    screen.blit(title, (sw // 2 - title.get_width() // 2, 40))
    pygame.draw.line(screen, (60, 60, 80), (sw // 4, 118), (3 * sw // 4, 118), 2)

    DIM = (90, 90, 100)
    HI = (255, 255, 255)
    VAL = (255, 210, 80)
    ITEM_Y = 160
    SPACING = 72

    for i, item_label in enumerate(_SETTINGS_ITEMS):
        y = ITEM_Y + i * SPACING
        selected = (i == settings_cursor)
        text_color = HI if selected else DIM

        if selected:
            backing = pygame.Surface((sw - 200, 54), pygame.SRCALPHA)
            backing.fill((80, 80, 120, 70))
            screen.blit(backing, (100, y - 8))
            arr = renderer._font_hud.render(">", True, (255, 200, 80))
            screen.blit(arr, (72, y + 10))

        lbl = renderer._font_hud.render(item_label, True, text_color)
        screen.blit(lbl, (120, y))

        vx = sw * 3 // 4
        if i == _SETTINGS_CAMERA:
            cam_label = next((lb for ix, ok, lb in cam_probe_cache if ix == cam_index), f"{cam_index}: ?")
            avail = next((ok for ix, ok, lb in cam_probe_cache if ix == cam_index), None)
            col = (80, 220, 80) if avail else (220, 80, 80) if avail is False else VAL
            v = renderer._font_hud.render(f"< {cam_label} >", True, col)
        elif i == _SETTINGS_MODE:
            v = renderer._font_hud.render(f"< {detect_mode.upper()} >", True, VAL)
        elif i == _SETTINGS_PRESET:
            if detect_mode == "hsv":
                v = renderer._font_hud.render(f"< {_COLOR_PRESETS[preset_idx][0]} >", True, VAL)
            else:
                v = renderer._font_hud.render("(HSV mode only)", True, DIM)
        elif i == _SETTINGS_WINDOW:
            label_str = "Fullscreen (borderless)" if fullscreen else "Windowed"
            v = renderer._font_hud.render(f"< {label_str} >", True, VAL)
        elif i == _SETTINGS_CALIBRATE:
            v = renderer._font_hud.render("ENTER to launch", True, DIM)
        else:
            v = renderer._font_hud.render("ENTER / ESC", True, DIM)
        screen.blit(v, (vx - v.get_width(), y))

    hint = renderer._font_board.render(
        "UP/DOWN  navigate    LEFT/RIGHT  change value    ENTER  confirm    ESC  back",
        True, (70, 70, 85),
    )
    screen.blit(hint, (sw // 2 - hint.get_width() // 2, sh - 44))


def _camera_error_screen(screen: pygame.Surface, device_index: int) -> None:
    """Wait on a readable error screen (ESC/close quits) — the volunteer
    needs time to read it; never start the game loop on a dead capture."""
    font = pygame.font.Font(None, 44)
    small = pygame.font.Font(None, 32)
    lines = [
        (font, f"Camera {device_index} failed to open."),
        (small, "Check the USB cable, close apps using the camera (Teams/Zoom),"),
        (small, "then run:  python -m src.tools.list_cameras"),
        (small, "and set camera.device_index in config/config.yaml."),
        (small, ""),
        (small, "Press ESC to exit."),
    ]
    clock = pygame.time.Clock()
    while True:
        for event in pygame.event.get():
            if event.type == pygame.QUIT or (event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE):
                return
        screen.fill((18, 18, 24))
        y = screen.get_height() // 2 - 120
        for f, text in lines:
            surf = f.render(text, True, (255, 255, 255))
            screen.blit(surf, (screen.get_width() // 2 - surf.get_width() // 2, y))
            y += 48
        pygame.display.flip()
        clock.tick(30)


def run(config: AppConfig) -> None:
    # A leaked SDL_VIDEODRIVER=dummy (used by tests/asset generators) makes
    # SDL "create" an invisible window and report success — strip it.
    driver_env = os.environ.get("SDL_VIDEODRIVER", "")
    if driver_env.lower() in ("dummy", "offscreen"):
        log.warning("SDL_VIDEODRIVER=%s found in environment — unsetting it so a real window opens", driver_env)
        os.environ.pop("SDL_VIDEODRIVER")
        pygame.display.quit()  # re-init picks up the corrected environment
    pygame.init()
    # `size` is the game's logical coordinate space (all gameplay, detection
    # scaling, and rendering happen at this resolution). In fullscreen we open
    # a borderless window at desktop resolution and upscale the logical canvas
    # to it — exclusive fullscreen and SCALED both proved unreliable here
    # (hidden window without focus / "no fast renderer available").
    size = (config.display.window_width, config.display.window_height)
    if config.display.fullscreen:
        os.environ["SDL_VIDEO_WINDOW_POS"] = "0,0"
        try:
            screen = pygame.display.set_mode((0, 0), pygame.NOFRAME)
        except pygame.error as exc:
            log.warning("borderless fullscreen failed (%s) — falling back to windowed", exc)
            screen = pygame.display.set_mode(size)
    else:
        screen = pygame.display.set_mode(size)
    pygame.display.set_caption("Slice Rush")
    log.info(
        "display window: %dx%d (logical canvas %dx%d), SDL driver: %s",
        *screen.get_size(), *size, pygame.display.get_driver(),
    )

    # Best-effort: bring the window to the front (Windows won't give a
    # terminal-launched process foreground on its own).
    try:
        import ctypes

        hwnd = pygame.display.get_wm_info().get("window")
        if hwnd:
            NOSIZE_NOMOVE = 0x0003
            ctypes.windll.user32.ShowWindow(hwnd, 9)  # SW_RESTORE
            ctypes.windll.user32.SetWindowPos(hwnd, -1, 0, 0, 0, 0, NOSIZE_NOMOVE)  # topmost
            ctypes.windll.user32.SetWindowPos(hwnd, -2, 0, 0, 0, 0, NOSIZE_NOMOVE)  # release topmost
            ctypes.windll.user32.SetForegroundWindow(hwnd)
    except Exception:  # purely cosmetic — never fail startup over this
        pass

    # Splash while the camera opens (DirectShow can take a few seconds).
    sw, sh = screen.get_size()
    screen.fill((18, 18, 24))
    splash_font = pygame.font.Font(None, 96)
    small_font = pygame.font.Font(None, 40)
    title = splash_font.render("SLICE RUSH", True, (255, 220, 80))
    status = small_font.render("Starting camera…", True, (200, 200, 200))
    screen.blit(title, (sw // 2 - title.get_width() // 2, sh // 2 - 100))
    screen.blit(status, (sw // 2 - status.get_width() // 2, sh // 2 + 20))
    pygame.display.flip()

    leaderboard = Leaderboard(config.persistence.db_path)
    audio = AudioPlayer(config.audio, config.assets.sounds_dir)

    capture = CameraCapture(config.camera)
    if not capture.open():
        _camera_error_screen(screen, config.camera.device_index)
        pygame.quit()
        return

    dt_camera = 1.0 / config.camera.target_fps
    if config.detection_mode == "hand":
        detector = HandDetector(config.hand_detection)
        trackers = {"tip": MarkerTracker(config.tracking.kalman, dt_camera)}
    else:
        detector = ColorBlobDetector(config.detection)
        trackers = {m.name: MarkerTracker(config.tracking.kalman, dt_camera) for m in config.detection.markers}
    trail = SliceTrail(config.game.slice.trail_max_points)
    rng = random.Random()
    spawner = EntitySpawner(config.game, config.assets, size[0], size[1], rng)
    effects = EffectsSystem(config.effects, config.game.physics, rng)
    effects.set_screen_height(size[1])
    state = GameStateMachine(config.game)
    renderer = Renderer(config, screen)
    renderer.leaderboard_rows = leaderboard.get_top(config.persistence.leaderboard_top_n)

    # Settings screen state
    config_path = sys.argv[1] if len(sys.argv) > 1 else "config/config.yaml"
    settings_cursor: int = 0
    settings_cam_index: int = config.camera.device_index
    settings_detect_mode: str = config.detection_mode
    settings_preset_idx: int = 0
    settings_fullscreen: bool = config.display.fullscreen
    cam_probe_cache: list = []
    cam_probe_done: bool = False

    def _apply_settings() -> None:
        nonlocal detector, trackers, settings_cam_index, settings_detect_mode, screen, sw, sh
        updates: dict = {}

        if settings_cam_index != config.camera.device_index:
            config.camera.device_index = settings_cam_index
            updates["camera"] = {"device_index": settings_cam_index}
            capture.release()
            if not capture.open():
                log.warning("camera %d failed to open — reverting to previous index", settings_cam_index)
                config.camera.device_index = settings_cam_index  # already set; user must fix via settings

        if settings_detect_mode != config.detection_mode:
            config.detection_mode = settings_detect_mode
            updates["detection_mode"] = settings_detect_mode

        if settings_detect_mode == "hsv":
            # Ensure config.detection exists (it's None when launched in hand mode)
            if config.detection is None:
                _, lower, upper = _COLOR_PRESETS[settings_preset_idx]
                config.detection = DetectionConfig(
                    markers=[MarkerConfig(
                        name="tip",
                        hsv_lower=tuple(lower),
                        hsv_upper=tuple(upper),
                        min_area_px=200,
                        max_area_px=30000,
                    )],
                    blur_kernel=5,
                    morphology=MorphologyConfig(
                        open_kernel=3, open_iterations=1,
                        close_kernel=7, close_iterations=2,
                    ),
                )
            # Apply preset if it differs from current marker bounds
            _, lower, upper = _COLOR_PRESETS[settings_preset_idx]
            tip = next((m for m in config.detection.markers if m.name == "tip"), None)
            if tip is not None and (list(tip.hsv_lower) != lower or list(tip.hsv_upper) != upper):
                tip.hsv_lower = tuple(lower)
                tip.hsv_upper = tuple(upper)
            updates.setdefault("detection", {})["markers"] = [
                {"name": m.name, "hsv_lower": list(m.hsv_lower), "hsv_upper": list(m.hsv_upper),
                 "min_area_px": m.min_area_px, "max_area_px": m.max_area_px}
                for m in config.detection.markers
            ]
            detector = ColorBlobDetector(config.detection)
            trackers = {m.name: MarkerTracker(config.tracking.kalman, dt_camera)
                        for m in config.detection.markers}
        else:
            if config.hand_detection is None:
                config.hand_detection = HandDetectionConfig()
            detector = HandDetector(config.hand_detection)
            trackers = {"tip": MarkerTracker(config.tracking.kalman, dt_camera)}

        if settings_fullscreen != config.display.fullscreen:
            config.display.fullscreen = settings_fullscreen
            updates.setdefault("display", {})["fullscreen"] = settings_fullscreen
            if settings_fullscreen:
                os.environ["SDL_VIDEO_WINDOW_POS"] = "0,0"
                try:
                    screen = pygame.display.set_mode((0, 0), pygame.NOFRAME)
                except pygame.error:
                    screen = pygame.display.set_mode((config.display.window_width, config.display.window_height))
            else:
                screen = pygame.display.set_mode((config.display.window_width, config.display.window_height))
            renderer._display = screen
            sw, sh = screen.get_size()

        if updates:
            save_config(config_path, updates)
            log.info("settings saved: %s", list(updates.keys()))

    log.info(
        "game running — %s window is up (attract screen). SPACE starts, ESC quits, F1 debug.",
        "fullscreen" if config.display.fullscreen else "windowed",
    )
    clock = pygame.time.Clock()
    entities: list[FallingEntity] = []
    next_entity_id = 1
    last_spawn_time = 0.0
    last_seen_frame_id = 0
    last_tip_detection_time = time.monotonic()
    name_buffer = ""
    session_written = False
    prev_phase = state.phase
    smoothed_tip: tuple[float, float] | None = None
    last_countdown_int = -1
    measured_cam_fps = 0.0
    cam_frame_times: list[float] = []

    def write_session(name: str) -> None:
        nonlocal session_written, name_buffer
        if session_written:
            return
        record = state.finalize_session(name.strip() or "Player")
        leaderboard.insert_session(record)
        session_written = True
        name_buffer = ""

    render_frame: np.ndarray | None = None
    running = True
    while running:
        dt = clock.tick(config.display.fps_cap) / 1000.0
        now = time.monotonic()

        # ---------------------------------------------------------- events
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False

            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_F1:
                    renderer.show_debug = not renderer.show_debug

                # ---- Main menu ----
                elif state.phase is GamePhase.IDLE_ATTRACT:
                    if event.key == pygame.K_UP:
                        state.menu_cursor = (state.menu_cursor - 1) % 3
                    elif event.key == pygame.K_DOWN:
                        state.menu_cursor = (state.menu_cursor + 1) % 3
                    elif event.key in (pygame.K_RETURN, pygame.K_SPACE):
                        if state.menu_cursor == 0:          # Start
                            state.start_new_game()
                            entities.clear()
                            trail.clear()
                            session_written = False
                            name_buffer = ""
                            last_tip_detection_time = now
                            last_countdown_int = -1
                        elif state.menu_cursor == 1:        # Settings
                            if not cam_probe_done:
                                screen.fill((18, 18, 24))
                                msg = renderer._font_hud.render(
                                    "Scanning cameras… (this takes a few seconds)", True, (200, 200, 200)
                                )
                                screen.blit(msg, (sw // 2 - msg.get_width() // 2, sh // 2))
                                pygame.display.flip()
                                cam_probe_cache[:] = _probe_cameras()
                                cam_probe_done = True
                            settings_cam_index = config.camera.device_index
                            settings_detect_mode = config.detection_mode
                            settings_fullscreen = config.display.fullscreen
                            settings_cursor = 0
                            state.enter_settings()
                        elif state.menu_cursor == 2:        # Exit
                            running = False
                    elif event.key == pygame.K_ESCAPE:
                        running = False

                # ---- Settings screen ----
                elif state.phase is GamePhase.SETTINGS_MENU:
                    if event.key == pygame.K_UP:
                        settings_cursor = (settings_cursor - 1) % len(_SETTINGS_ITEMS)
                    elif event.key == pygame.K_DOWN:
                        settings_cursor = (settings_cursor + 1) % len(_SETTINGS_ITEMS)
                    elif event.key == pygame.K_LEFT:
                        if settings_cursor == _SETTINGS_CAMERA:
                            settings_cam_index = max(0, settings_cam_index - 1)
                        elif settings_cursor == _SETTINGS_MODE:
                            settings_detect_mode = "hand" if settings_detect_mode == "hsv" else "hsv"
                        elif settings_cursor == _SETTINGS_PRESET and settings_detect_mode == "hsv":
                            settings_preset_idx = (settings_preset_idx - 1) % len(_COLOR_PRESETS)
                        elif settings_cursor == _SETTINGS_WINDOW:
                            settings_fullscreen = not settings_fullscreen
                    elif event.key == pygame.K_RIGHT:
                        if settings_cursor == _SETTINGS_CAMERA:
                            settings_cam_index = min(5, settings_cam_index + 1)
                        elif settings_cursor == _SETTINGS_MODE:
                            settings_detect_mode = "hand" if settings_detect_mode == "hsv" else "hsv"
                        elif settings_cursor == _SETTINGS_PRESET and settings_detect_mode == "hsv":
                            settings_preset_idx = (settings_preset_idx + 1) % len(_COLOR_PRESETS)
                        elif settings_cursor == _SETTINGS_WINDOW:
                            settings_fullscreen = not settings_fullscreen
                    elif event.key == pygame.K_RETURN:
                        if settings_cursor == _SETTINGS_CALIBRATE:
                            root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                            subprocess.Popen([sys.executable, "-m", "src.tools.calibrate"], cwd=root)
                        elif settings_cursor == _SETTINGS_BACK:
                            _apply_settings()
                            state.exit_settings_to_idle()
                            settings_cursor = 0
                    elif event.key == pygame.K_ESCAPE:
                        _apply_settings()
                        state.exit_settings_to_idle()
                        settings_cursor = 0

                # ---- In-game ----
                else:
                    if event.key == pygame.K_ESCAPE:
                        running = False
                    elif event.key == pygame.K_r:
                        state.abort_to_idle()
                        entities.clear()
                        trail.clear()
                    elif state.phase is GamePhase.SCORE_SUBMIT and config.persistence.name_entry:
                        if event.key == pygame.K_RETURN:
                            write_session(name_buffer)
                        elif event.key == pygame.K_BACKSPACE:
                            name_buffer = name_buffer[:-1]

            elif event.type == pygame.TEXTINPUT and state.phase is GamePhase.SCORE_SUBMIT:
                if config.persistence.name_entry and len(name_buffer) < config.persistence.name_max_chars:
                    if event.text.isprintable():
                        name_buffer += event.text

        # ---------------------------------------------------------- camera + vision (camera clock)
        capture.maintain()
        frame, frame_id = capture.read_latest()
        camera_stale = capture.seconds_since_last_frame() > CAMERA_STALE_AFTER_S
        state.set_timer_paused(camera_stale)

        if frame is not None and frame_id != last_seen_frame_id:
            last_seen_frame_id = frame_id
            cam_frame_times.append(now)
            cam_frame_times = [t for t in cam_frame_times if now - t < 2.0]
            measured_cam_fps = len(cam_frame_times) / 2.0

            detections = detector.detect(frame)
            # Detection coords are in camera-frame pixels; the game world is in
            # window pixels. Cameras may negotiate a different resolution than
            # requested (e.g. 1080p instead of 720p), so scale every frame.
            sx = size[0] / frame.shape[1]
            sy = size[1] / frame.shape[0]
            for name, tracker in trackers.items():
                det = detections.get(name)
                measurement = None
                if det is not None and det.found:
                    measurement = (det.center[0] * sx, det.center[1] * sy)
                smoothed = tracker.update(measurement)
                if name == "tip":
                    smoothed_tip = smoothed
                    if measurement is not None:
                        last_tip_detection_time = now

            tip_tracker = trackers["tip"]
            if state.phase in (GamePhase.PLAYING, GamePhase.ROUND_TRANSITION):
                if not tip_tracker.is_lost() and smoothed_tip is not None:
                    trail.add_point(smoothed_tip)
                    segment = trail.get_last_segment()
                    if segment is not None and tip_tracker.speed_px_s() >= config.game.slice.min_speed_px_s:
                        hits = resolve_slices(segment, entities)
                        for e in hits:
                            if e.entity_type is EntityType.FRUIT:
                                heart_restored = state.register_fruit_hit(e.points)
                                effects.spawn_fruit_slice(e, state.combo)
                                audio.play("slice")
                                if heart_restored:
                                    effects.spawn_heart_restore(e.x, e.y - 40)
                            else:
                                state.register_bad_hit()
                                effects.spawn_bad_hit(e)
                                audio.play("bomb")
                        if hits:
                            entities = [e for e in entities if not e.sliced]
                else:
                    trail.clear()

            if config.detection_mode == "hand":
                ov = detector.get_last_overlay()
                render_frame = ov if ov is not None else frame
                renderer.debug_mask = cv2.cvtColor(ov, cv2.COLOR_BGR2GRAY) if (renderer.show_debug and ov is not None) else None
            else:
                render_frame = frame
                renderer.debug_mask = detector.get_last_mask("tip") if renderer.show_debug else None

        # ---------------------------------------------------------- game tick (render clock)
        state.tick(dt)

        # phase-entry sounds / bookkeeping
        if state.phase is not prev_phase:
            if state.phase is GamePhase.PLAYING and prev_phase is GamePhase.COUNTDOWN:
                audio.play("go")
            elif state.phase is GamePhase.ROUND_TRANSITION:
                audio.play("round_clear")
            elif state.phase is GamePhase.GAME_OVER:
                audio.play("game_over")
            elif state.phase is GamePhase.IDLE_ATTRACT:
                renderer.leaderboard_rows = leaderboard.get_top(config.persistence.leaderboard_top_n)
                entities.clear()
                trail.clear()
            prev_phase = state.phase
        if state.phase is GamePhase.COUNTDOWN:
            current_int = int(state.countdown_timer)
            if current_int != last_countdown_int:
                audio.play("beep")
                last_countdown_int = current_int

        # spawning: real rounds while PLAYING, ambient fruit while idle
        if state.phase is GamePhase.PLAYING:
            interval = spawn_interval(
                state.round_number,
                config.game.difficulty.base_spawn_interval_seconds,
                config.game.difficulty.spawn_interval_decay_per_round,
                config.game.difficulty.min_spawn_interval_seconds,
            )
            if now - last_spawn_time >= interval:
                for _ in range(config.game.difficulty.spawn_count_per_interval):
                    entities.append(spawner.spawn(state.round_number, next_entity_id))
                    next_entity_id += 1
                last_spawn_time = now
        elif state.phase is GamePhase.IDLE_ATTRACT:
            if now - last_spawn_time >= ATTRACT_SPAWN_INTERVAL_S:
                entities.append(spawner.spawn(1, next_entity_id, fruit_only=True))
                next_entity_id += 1
                last_spawn_time = now
        elif state.phase is GamePhase.SETTINGS_MENU:
            pass  # no spawning during settings

        spawner.update(entities, dt)
        for e in entities:
            if e.missed and state.phase in (GamePhase.PLAYING, GamePhase.ROUND_TRANSITION):
                state.register_miss()
        entities = [e for e in entities if not e.missed and not spawner.is_off_screen(e)]
        effects.update(dt)

        # idle timeout: unattended COUNTDOWN/PLAYING with no tip detections
        if state.phase in (GamePhase.COUNTDOWN, GamePhase.PLAYING):
            if now - last_tip_detection_time > config.persistence.idle_timeout_seconds:
                log.info("idle timeout — returning to attract mode (no session written)")
                state.abort_to_idle()

        # score submit: auto-finalize on timeout or when name entry disabled
        if state.phase is GamePhase.SCORE_SUBMIT and not session_written:
            if not config.persistence.name_entry or state.submit_timer <= 0:
                write_session(name_buffer)
        if state.phase is GamePhase.GAME_OVER:
            session_written = False  # armed for the upcoming SCORE_SUBMIT

        # ---------------------------------------------------------- render
        if state.phase is GamePhase.SETTINGS_MENU:
            _draw_settings_screen(
                screen, renderer, settings_cursor,
                settings_cam_index, cam_probe_cache,
                settings_detect_mode, settings_preset_idx,
                settings_fullscreen,
            )
            pygame.display.flip()
            continue

        if renderer.show_debug:
            tip_tracker = trackers["tip"]
            renderer.debug_lines = [
                f"cam fps: {measured_cam_fps:.1f}  render fps: {clock.get_fps():.1f}",
                f"tip lost: {tip_tracker.is_lost()}  speed: {tip_tracker.speed_px_s():.0f}/{config.game.slice.min_speed_px_s} px/s",
            ]
        renderer.draw(
            render_frame,
            frame_id,
            entities,
            trail.points(),
            state,
            effects,
            camera_stale,
            name_buffer=name_buffer,
            tip_pos=smoothed_tip,
            dt=dt,
        )
        pygame.display.flip()

    capture.release()
    leaderboard.close()
    pygame.quit()


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    config_path = sys.argv[1] if len(sys.argv) > 1 else "config/config.yaml"
    config = load_config(config_path)
    run(config)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
