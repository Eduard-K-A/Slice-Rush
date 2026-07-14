"""Slice Rush orchestration — main.py wires modules together and contains
no detection or game-rule logic itself.

Run: python -m src.main
Volunteer keys: SPACE start · R abort to idle · F1 debug overlay · ESC quit.
"""
from __future__ import annotations

import logging
import os
import random
import sys
import time

# Booth robustness: SDL minimizes fullscreen windows on focus loss by
# default, which makes the game "vanish" when launched from a terminal.
os.environ.setdefault("SDL_VIDEO_MINIMIZE_ON_FOCUS_LOSS", "0")

import cv2
import numpy as np
import pygame

from src.config_loader import AppConfig, load_config
from src.game.audio import AudioPlayer
from src.game.difficulty import spawn_interval
from src.game.effects import EffectsSystem
from src.game.entities import EntitySpawner, EntityType, FallingEntity
from src.game.game_state import GamePhase, GameStateMachine
from src.game.renderer import Renderer
from src.game.slice_logic import SliceTrail, resolve_slices
from src.persistence.leaderboard import Leaderboard
from src.vision.capture import CameraCapture
from src.vision.detection import ColorBlobDetector
from src.vision.tracking import MarkerTracker

log = logging.getLogger("slice_rush")

ATTRACT_SPAWN_INTERVAL_S = 1.5
CAMERA_STALE_AFTER_S = 1.0


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

    detector = ColorBlobDetector(config.detection)
    dt_camera = 1.0 / config.camera.target_fps
    trackers = {m.name: MarkerTracker(config.tracking.kalman, dt_camera) for m in config.detection.markers}
    trail = SliceTrail(config.game.slice.trail_max_points)
    rng = random.Random()
    spawner = EntitySpawner(config.game, config.assets, size[0], size[1], rng)
    effects = EffectsSystem(config.effects, config.game.physics, rng)
    effects.set_screen_height(size[1])
    state = GameStateMachine(config.game)
    renderer = Renderer(config, screen)
    renderer.leaderboard_rows = leaderboard.get_top(config.persistence.leaderboard_top_n)

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

    running = True
    while running:
        dt = clock.tick(config.display.fps_cap) / 1000.0
        now = time.monotonic()

        # ---------------------------------------------------------- events
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    running = False
                elif event.key == pygame.K_F1:
                    renderer.show_debug = not renderer.show_debug
                elif event.key == pygame.K_r:
                    state.abort_to_idle()
                    entities.clear()
                    trail.clear()
                elif event.key == pygame.K_SPACE and state.phase is GamePhase.IDLE_ATTRACT:
                    state.start_new_game()
                    entities.clear()
                    trail.clear()
                    session_written = False
                    name_buffer = ""
                    last_tip_detection_time = now
                    last_countdown_int = -1
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
                                state.register_fruit_hit(e.points)
                                effects.spawn_fruit_slice(e, state.combo)
                                audio.play("slice")
                            else:
                                state.register_bad_hit()
                                effects.spawn_bad_hit(e)
                                audio.play("bomb")
                        if hits:
                            entities = [e for e in entities if not e.sliced]
                else:
                    trail.clear()

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
                entities.append(spawner.spawn(state.round_number, next_entity_id))
                next_entity_id += 1
                last_spawn_time = now
        elif state.phase is GamePhase.IDLE_ATTRACT:
            if now - last_spawn_time >= ATTRACT_SPAWN_INTERVAL_S:
                entities.append(spawner.spawn(1, next_entity_id, fruit_only=True))
                next_entity_id += 1
                last_spawn_time = now

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
        if renderer.show_debug:
            tip_tracker = trackers["tip"]
            renderer.debug_lines = [
                f"cam fps: {measured_cam_fps:.1f}  render fps: {clock.get_fps():.1f}",
                f"tip lost: {tip_tracker.is_lost()}  speed: {tip_tracker.speed_px_s():.0f}/{config.game.slice.min_speed_px_s} px/s",
            ]
        renderer.draw(
            frame,
            frame_id,
            entities,
            trail.points(),
            state,
            effects,
            camera_stale,
            name_buffer=name_buffer,
            tip_pos=smoothed_tip,
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
