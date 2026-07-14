"""Pygame rendering: camera-feed background, fruit sprites, effects, HUD,
phase overlays, operator debug overlay.

Layer order per frame (bottom -> top): camera feed -> falling entities ->
halves -> particles -> trail -> popups -> red flash -> HUD -> phase
overlays -> debug overlay. Screen shake offsets the world layers only,
never the HUD.
"""
from __future__ import annotations

import logging
import os
from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np
import pygame

from src.config_loader import AppConfig
from src.game.effects import EffectsSystem
from src.game.entities import FallingEntity
from src.game.game_state import GamePhase, GameStateMachine
from src.persistence.db import SessionRecord
from src.tools.generate_sprites import expected_files

log = logging.getLogger(__name__)

WHITE = (255, 255, 255)
HEART_RED = (230, 60, 60)
DIM = (0, 0, 0, 160)


class Renderer:
    def __init__(self, config: AppConfig, screen: pygame.Surface):
        self._config = config
        # All drawing happens on a logical-resolution canvas; draw() scales it
        # to the real window at the end (they differ in borderless fullscreen).
        self._display = screen
        self._w = config.display.window_width
        self._h = config.display.window_height
        self._screen = pygame.Surface((self._w, self._h))
        self._sprites: Dict[str, pygame.Surface] = {}
        self._load_sprites()
        self._font_hud = self._load_font(36)
        self._font_banner = self._load_font(96)
        self._font_countdown = self._load_font(220)
        self._font_board = self._load_font(32)
        self._camera_surface: Optional[pygame.Surface] = None
        self._camera_frame_id = -1
        self.leaderboard_rows: List[SessionRecord] = []
        self.show_debug = config.display.show_debug_overlay
        self.debug_mask: Optional[np.ndarray] = None
        self.debug_lines: List[str] = []

    # ------------------------------------------------------------------ assets

    def _load_font(self, size: int) -> pygame.font.Font:
        fonts_dir = "assets/fonts"
        if os.path.isdir(fonts_dir):
            for f in sorted(os.listdir(fonts_dir)):
                if f.lower().endswith(".ttf"):
                    try:
                        return pygame.font.Font(os.path.join(fonts_dir, f), size)
                    except pygame.error:
                        break
        return pygame.font.Font(None, size)

    def _load_sprites(self) -> None:
        px = self._config.assets.entity_sprite_px
        for filename in expected_files():
            key = filename[:-4]
            path = os.path.join(self._config.assets.sprites_dir, filename)
            try:
                img = pygame.image.load(path).convert_alpha()
                self._sprites[key] = pygame.transform.smoothscale(img, (px, px))
            except (pygame.error, FileNotFoundError) as exc:
                log.warning("sprite %s failed to load (%s) — using circle placeholder", path, exc)
                placeholder = pygame.Surface((px, px), pygame.SRCALPHA)
                color = (90, 200, 90) if "half" not in key and key not in ("bomb", "rock") else (160, 60, 60)
                pygame.draw.circle(placeholder, color, (px // 2, px // 2), px // 2)
                self._sprites[key] = placeholder

    # ------------------------------------------------------------------ camera background

    def _camera_background(self, frame: Optional[np.ndarray], frame_id: int) -> Optional[pygame.Surface]:
        if frame is not None and frame_id != self._camera_frame_id:
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            surf = pygame.image.frombuffer(rgb.tobytes(), (rgb.shape[1], rgb.shape[0]), "RGB")
            self._camera_surface = pygame.transform.scale(surf, (self._w, self._h))
            self._camera_frame_id = frame_id
        return self._camera_surface

    # ------------------------------------------------------------------ draw

    def draw(
        self,
        frame: Optional[np.ndarray],
        frame_id: int,
        entities: List[FallingEntity],
        trail_points: List[Tuple[float, float]],
        state: GameStateMachine,
        effects: EffectsSystem,
        camera_stale: bool,
        name_buffer: str = "",
        tip_pos: Optional[Tuple[float, float]] = None,
    ) -> None:
        screen = self._screen
        shake = effects.shake_offset()
        world = pygame.Surface((self._w, self._h))
        world.fill((18, 18, 24))

        cam = self._camera_background(frame, frame_id)
        if cam is not None:
            world.blit(cam, (0, 0))

        for e in entities:
            self._draw_sprite(world, e.subtype, e.position, e.rotation_deg)
        for h in effects.halves:
            self._draw_sprite(world, h.sprite_key, h.position, h.rotation_deg)
        for p in effects.particles:
            fade = max(0.0, 1.0 - p.age_s / p.lifetime_s)
            r = max(1, int(p.radius_px * fade))
            pygame.draw.circle(world, p.color, (int(p.position[0]), int(p.position[1])), r)
        self._draw_trail(world, trail_points)
        for s in effects.popups:
            fade = max(0.0, 1.0 - s.age_s / s.lifetime_s)
            text = self._font_hud.render(s.text, True, s.color)
            text.set_alpha(int(255 * fade))
            world.blit(text, (int(s.position[0]) - text.get_width() // 2, int(s.position[1])))

        screen.blit(world, shake)

        alpha = effects.red_flash_alpha()
        if alpha > 0:
            flash = pygame.Surface((self._w, self._h), pygame.SRCALPHA)
            flash.fill((220, 30, 30, alpha))
            screen.blit(flash, (0, 0))

        phase = state.phase
        if phase in (GamePhase.PLAYING, GamePhase.ROUND_TRANSITION, GamePhase.COUNTDOWN):
            self._draw_hud(state, tip_pos)
        if phase is GamePhase.IDLE_ATTRACT:
            self._draw_idle()
        elif phase is GamePhase.COUNTDOWN:
            self._draw_countdown(state)
        elif phase is GamePhase.ROUND_TRANSITION:
            self._draw_round_transition(state)
        elif phase is GamePhase.GAME_OVER:
            self._draw_game_over(state)
        elif phase is GamePhase.SCORE_SUBMIT:
            self._draw_score_submit(state, name_buffer)

        if camera_stale:
            self._banner_top("CAMERA DISCONNECTED — reconnecting…", HEART_RED)
        if self.show_debug:
            self._draw_debug()

        # Composite the logical canvas onto the real window.
        if self._screen.get_size() != self._display.get_size():
            pygame.transform.scale(self._screen, self._display.get_size(), self._display)
        else:
            self._display.blit(self._screen, (0, 0))

    # ------------------------------------------------------------------ pieces

    def _draw_sprite(self, target: pygame.Surface, key: str, position: np.ndarray, rotation_deg: float) -> None:
        sprite = self._sprites.get(key)
        if sprite is None:
            return
        rotated = pygame.transform.rotozoom(sprite, -rotation_deg, 1.0)
        rect = rotated.get_rect(center=(int(position[0]), int(position[1])))
        target.blit(rotated, rect)

    def _draw_trail(self, target: pygame.Surface, points: List[Tuple[float, float]]) -> None:
        if len(points) < 2:
            return
        n = len(points)
        for i in range(n - 1):
            frac = (i + 1) / n
            width = max(2, int(12 * frac))
            p1 = (int(points[i][0]), int(points[i][1]))
            p2 = (int(points[i + 1][0]), int(points[i + 1][1]))
            pygame.draw.line(target, (255, 120, 220), p1, p2, width + 6)
            pygame.draw.line(target, WHITE, p1, p2, width)

    def _draw_hud(self, state: GameStateMachine, tip_pos: Optional[Tuple[float, float]]) -> None:
        screen = self._screen
        # hearts top-left
        for i in range(self._config.game.starting_hearts):
            x, y, r = 34 + i * 52, 40, 18
            filled = i < state.hearts
            color = HEART_RED if filled else (90, 90, 90)
            pygame.draw.circle(screen, color, (x - 8, y), r // 1, 0 if filled else 3)
            pygame.draw.circle(screen, color, (x + 8, y), r, 0 if filled else 3)
            pygame.draw.polygon(
                screen, color, [(x - 24, y + 6), (x + 24, y + 6), (x, y + 38)], 0 if filled else 3
            )
        # score top-right
        score = self._font_banner.render(str(state.score), True, WHITE)
        screen.blit(score, (self._w - score.get_width() - 30, 16))
        # round + timer bar top-center
        round_text = self._font_hud.render(
            f"ROUND {state.round_number}  —  target {state.current_round_target()}", True, WHITE
        )
        screen.blit(round_text, (self._w // 2 - round_text.get_width() // 2, 20))
        duration = self._config.game.timers.round_duration_seconds
        frac = max(0.0, min(1.0, state.round_timer / duration))
        bar_w = 360
        color = (90, 200, 90) if state.round_timer >= 5 else (230, 180, 60) if state.round_timer >= 2 else HEART_RED
        pygame.draw.rect(screen, (60, 60, 60), pygame.Rect(self._w // 2 - bar_w // 2, 64, bar_w, 14), border_radius=7)
        pygame.draw.rect(
            screen, color, pygame.Rect(self._w // 2 - bar_w // 2, 64, int(bar_w * frac), 14), border_radius=7
        )
        # combo near the tip
        if state.combo >= 2 and tip_pos is not None:
            combo = self._font_hud.render(f"x{state.combo}", True, (255, 220, 80))
            screen.blit(combo, (int(tip_pos[0]) + 24, int(tip_pos[1]) - 40))

    def _dim(self) -> None:
        overlay = pygame.Surface((self._w, self._h), pygame.SRCALPHA)
        overlay.fill(DIM)
        self._screen.blit(overlay, (0, 0))

    def _center_text(self, font: pygame.font.Font, text: str, y: int, color=WHITE) -> None:
        surf = font.render(text, True, color)
        self._screen.blit(surf, (self._w // 2 - surf.get_width() // 2, y))

    def _banner_top(self, text: str, color) -> None:
        surf = self._font_hud.render(text, True, WHITE)
        pad = 14
        rect = pygame.Rect(
            self._w // 2 - surf.get_width() // 2 - pad, 100, surf.get_width() + 2 * pad, surf.get_height() + pad
        )
        pygame.draw.rect(self._screen, color, rect, border_radius=8)
        self._screen.blit(surf, (rect.x + pad, rect.y + pad // 2))

    def _draw_idle(self) -> None:
        self._dim()
        self._center_text(self._font_banner, "SLICE RUSH", 70, (255, 220, 80))
        self._center_text(self._font_hud, "— LEADERBOARD —", 190)
        y = 240
        if not self.leaderboard_rows:
            self._center_text(self._font_board, "No scores yet — be the first!", y)
        for rank, row in enumerate(self.leaderboard_rows, start=1):
            line = f"{rank:>2}.  {row.player_name:<14} {row.final_score:>6} pts   round {row.rounds_reached}"
            self._center_text(self._font_board, line, y)
            y += 38
        pulse = 128 + int(127 * abs(pygame.time.get_ticks() % 2000 - 1000) / 1000)
        start = self._font_hud.render("Press SPACE to start", True, (pulse, pulse, pulse))
        self._screen.blit(start, (self._w // 2 - start.get_width() // 2, self._h - 80))

    def _draw_countdown(self, state: GameStateMachine) -> None:
        remaining = state.countdown_timer
        label = "GO!" if remaining <= 0 else str(int(remaining) + 1)
        # scale-pop: biggest right after each integer boundary
        frac = remaining - int(remaining)
        size = 1.0 + 0.25 * frac
        text = self._font_countdown.render(label, True, (255, 220, 80))
        text = pygame.transform.rotozoom(text, 0, size)
        self._screen.blit(
            text, (self._w // 2 - text.get_width() // 2, self._h // 2 - text.get_height() // 2)
        )

    def _draw_round_transition(self, state: GameStateMachine) -> None:
        self._center_text(self._font_banner, f"ROUND {state.round_number - 1} CLEAR!", self._h // 2 - 130, (120, 230, 120))
        self._center_text(self._font_hud, f"Next target: {state.current_round_target()} pts", self._h // 2 + 10)

    def _draw_game_over(self, state: GameStateMachine) -> None:
        self._dim()
        self._center_text(self._font_banner, "GAME OVER", self._h // 2 - 160, HEART_RED)
        self._center_text(self._font_hud, f"Final score: {state.score}", self._h // 2)
        self._center_text(self._font_hud, f"Rounds reached: {state.round_number}", self._h // 2 + 50)

    def _draw_score_submit(self, state: GameStateMachine, name_buffer: str) -> None:
        self._dim()
        if self._config.persistence.name_entry:
            self._center_text(self._font_banner, f"{state.score} pts", self._h // 2 - 200, (255, 220, 80))
            self._center_text(self._font_hud, f"Enter name: {name_buffer}_", self._h // 2 - 40)
            self._center_text(self._font_hud, "Press ENTER to save", self._h // 2 + 20)
            self._center_text(
                self._font_board, f"auto-saving in {max(0, int(state.submit_timer))}s", self._h // 2 + 70, (180, 180, 180)
            )
        else:
            self._center_text(self._font_banner, "Score saved!", self._h // 2 - 60, (120, 230, 120))

    def _draw_debug(self) -> None:
        if self.debug_mask is not None:
            mask_small = cv2.resize(self.debug_mask, (320, 180))
            rgb = cv2.cvtColor(mask_small, cv2.COLOR_GRAY2RGB)
            surf = pygame.image.frombuffer(rgb.tobytes(), (320, 180), "RGB")
            self._screen.blit(surf, (self._w - 330, self._h - 190))
        y = self._h - 190 - 26 * len(self.debug_lines)
        for line in self.debug_lines:
            text = self._font_board.render(line, True, (120, 255, 120))
            self._screen.blit(text, (self._w - 330, y))
            y += 26
