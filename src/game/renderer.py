"""Pygame rendering: camera-feed background, fruit sprites, effects, HUD,
phase overlays, operator debug overlay.

Layer order per frame (bottom -> top): camera feed -> falling entities ->
halves -> splat blobs -> particles -> trail -> popups -> red flash -> HUD ->
phase overlays -> debug overlay. Screen shake offsets the world layers only,
never the HUD.
"""
from __future__ import annotations

import logging
import math
import os
import random
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
GOLD = (255, 215, 0)
SILVER = (210, 210, 210)
BRONZE = (205, 127, 50)
RANK_COLORS = [GOLD, SILVER, BRONZE]


def _hsv_color(hue: int, sat: int = 100, val: int = 100) -> Tuple[int, int, int]:
    c = pygame.Color(0)
    c.hsva = (hue % 360, sat, val, 100)
    return c.r, c.g, c.b


class Renderer:
    def __init__(self, config: AppConfig, screen: pygame.Surface):
        self._config = config
        self._display = screen
        self._w = config.display.window_width
        self._h = config.display.window_height
        self._screen = pygame.Surface((self._w, self._h))
        self._sprites: Dict[str, pygame.Surface] = {}
        self._load_sprites()
        self._font_hud = self._load_font(36)
        self._font_combo = self._load_font(64)
        self._font_score = self._load_font(112)
        self._font_banner = self._load_font(96)
        self._font_countdown = self._load_font(220)
        self._font_board = self._load_font(34)
        self._font_title = self._load_font(118)
        self._font_menu = self._load_font(44)   # idle screen menu items
        self._font_lb = self._load_font(62)     # idle screen leaderboard rows
        self._camera_surface: Optional[pygame.Surface] = None
        self._camera_frame_id = -1
        self.leaderboard_rows: List[SessionRecord] = []
        self.show_debug = config.display.show_debug_overlay
        self.debug_mask: Optional[np.ndarray] = None
        self.debug_lines: List[str] = []
        # Pre-allocated alpha surfaces reused every frame
        self._trail_surf = pygame.Surface((self._w, self._h), pygame.SRCALPHA)
        self._splat_surf = pygame.Surface((self._w, self._h), pygame.SRCALPHA)
        # Score shake state
        self._prev_score = 0
        self._score_shake_end_ms = 0
        # Combo pop scale state
        self._prev_combo = 0
        self._combo_pop_end_ms = 0
        # Background fruit animation (idle/menu screen)
        self._bg_fruits: List[dict] = []
        self._init_bg_fruits()

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

    # ------------------------------------------------------------------ background fruit animation

    def _init_bg_fruits(self) -> None:
        fruit_keys = [k for k in self._sprites if "half" not in k and k not in ("bomb", "rock")]
        if not fruit_keys:
            return
        r = random.Random(42)
        px = self._config.assets.entity_sprite_px
        for _ in range(8):
            key = r.choice(fruit_keys)
            scale = r.uniform(0.55, 0.95)
            scaled_px = max(16, int(px * scale))
            surf_base = pygame.transform.smoothscale(self._sprites[key], (scaled_px, scaled_px))
            self._bg_fruits.append({
                "surf_base": surf_base,
                "x": r.uniform(0.05, 0.95),
                "y": r.uniform(0.05, 0.95),
                "vx": r.uniform(-0.04, 0.04),
                "vy": r.uniform(-0.03, 0.03),
                "angle": r.uniform(0, 360),
                "spin": r.uniform(-25, 25),
                "alpha": r.randint(35, 70),
            })

    def _update_bg_fruits(self, dt: float) -> None:
        for f in self._bg_fruits:
            f["x"] += f["vx"] * dt
            f["y"] += f["vy"] * dt
            f["angle"] += f["spin"] * dt
            if f["x"] < -0.15: f["x"] = 1.15
            if f["x"] > 1.15:  f["x"] = -0.15
            if f["y"] < -0.15: f["y"] = 1.15
            if f["y"] > 1.15:  f["y"] = -0.15

    def _draw_bg_fruits(self) -> None:
        for f in self._bg_fruits:
            rotated = pygame.transform.rotozoom(f["surf_base"], f["angle"], 1.0)
            rotated.set_alpha(f["alpha"])
            x = int(f["x"] * self._w) - rotated.get_width() // 2
            y = int(f["y"] * self._h) - rotated.get_height() // 2
            self._screen.blit(rotated, (x, y))

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
        dt: float = 0.0,
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

        # Particles — splat blobs (large radius) drawn with alpha on separate surf;
        # small particles drawn directly for speed.
        self._splat_surf.fill((0, 0, 0, 0))
        for p in effects.particles:
            fade = max(0.0, 1.0 - p.age_s / p.lifetime_s)
            r = max(1, int(p.radius_px * fade))
            if p.radius_px > 8:
                alpha = int(210 * fade)
                pygame.draw.circle(
                    self._splat_surf, (*p.color, alpha),
                    (int(p.position[0]), int(p.position[1])), r,
                )
            else:
                pygame.draw.circle(world, p.color, (int(p.position[0]), int(p.position[1])), r)
        world.blit(self._splat_surf, (0, 0))

        self._draw_trail(world, trail_points)

        popup_font = self._font_hud
        for s in effects.popups:
            fade = max(0.0, 1.0 - s.age_s / s.lifetime_s)
            text = popup_font.render(s.text, True, s.color)
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
            self._draw_idle(state.menu_cursor, dt)
        elif phase is GamePhase.SETTINGS_MENU:
            pass  # drawn directly in main.py
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
        surf = self._trail_surf
        surf.fill((0, 0, 0, 0))
        n = len(points)
        ticks = pygame.time.get_ticks()
        for i in range(n - 1):
            frac = (i + 1) / n
            p1 = (int(points[i][0]), int(points[i][1]))
            p2 = (int(points[i + 1][0]), int(points[i + 1][1]))
            hue = (ticks // 4 + i * 50) % 360
            r, g, b = _hsv_color(hue)
            outer = max(6, int(34 * frac))
            mid = max(4, int(18 * frac))
            core = max(2, int(7 * frac))
            # Bloom glow
            pygame.draw.line(surf, (r, g, b, 35), p1, p2, outer + 12)
            # Colour band
            pygame.draw.line(surf, (r, g, b, 170), p1, p2, outer)
            # Bright mid
            pygame.draw.line(surf, (r, g, b, 220), p1, p2, mid)
            # White-hot core
            pygame.draw.line(surf, (255, 255, 255, 240), p1, p2, core)
        target.blit(surf, (0, 0))

    def _draw_hud(self, state: GameStateMachine, tip_pos: Optional[Tuple[float, float]]) -> None:
        screen = self._screen
        ticks = pygame.time.get_ticks()

        # --- hearts top-left ---
        for i in range(self._config.game.starting_hearts):
            x, y, r = 34 + i * 52, 40, 18
            filled = i < state.hearts
            color = HEART_RED if filled else (80, 80, 80)
            pygame.draw.circle(screen, color, (x - 8, y), r // 1, 0 if filled else 3)
            pygame.draw.circle(screen, color, (x + 8, y), r, 0 if filled else 3)
            pygame.draw.polygon(
                screen, color, [(x - 24, y + 6), (x + 24, y + 6), (x, y + 38)], 0 if filled else 3
            )

        # --- score top-right with shake on change ---
        if state.score != self._prev_score:
            self._score_shake_end_ms = ticks + 320
            self._prev_score = state.score
        shake_x, shake_y = 0, 0
        if ticks < self._score_shake_end_ms:
            frac = (self._score_shake_end_ms - ticks) / 320
            amp = int(9 * frac)
            shake_x = int(amp * math.sin(ticks * 0.18))
            shake_y = int(amp * math.cos(ticks * 0.27))
        score_str = str(state.score)
        shadow = self._font_score.render(score_str, True, (0, 0, 0))
        score_surf = self._font_score.render(score_str, True, (255, 235, 70))
        sx = self._w - score_surf.get_width() - 28 + shake_x
        sy = 8 + shake_y
        screen.blit(shadow, (sx + 4, sy + 4))
        screen.blit(score_surf, (sx, sy))

        # --- round label + timer bar top-center ---
        round_text = self._font_hud.render(
            f"ROUND {state.round_number}  —  target {state.current_round_target()}", True, WHITE
        )
        screen.blit(round_text, (self._w // 2 - round_text.get_width() // 2, 18))
        duration = self._config.game.timers.round_duration_seconds
        frac = max(0.0, min(1.0, state.round_timer / duration))
        bar_w = 360
        timer_color = (
            (90, 200, 90) if state.round_timer >= 5
            else (230, 180, 60) if state.round_timer >= 2
            else HEART_RED
        )
        pygame.draw.rect(screen, (55, 55, 55), pygame.Rect(self._w // 2 - bar_w // 2, 62, bar_w, 14), border_radius=7)
        pygame.draw.rect(
            screen, timer_color,
            pygame.Rect(self._w // 2 - bar_w // 2, 62, int(bar_w * frac), 14),
            border_radius=7,
        )

        # --- combo near tip with scale-pop ---
        if state.combo >= 2:
            if state.combo != self._prev_combo:
                self._combo_pop_end_ms = ticks + 350
                self._prev_combo = state.combo
            pop_t = max(0.0, (self._combo_pop_end_ms - ticks) / 350)
            scale = 1.0 + 0.9 * pop_t
            hue = (ticks // 5) % 360
            combo_color = _hsv_color(hue, 90, 100)
            combo_base = self._font_combo.render(f"x{state.combo}", True, combo_color)
            shadow_base = self._font_combo.render(f"x{state.combo}", True, (0, 0, 0))
            if scale > 1.02:
                combo_surf = pygame.transform.rotozoom(combo_base, 0, scale)
                shadow_surf = pygame.transform.rotozoom(shadow_base, 0, scale)
            else:
                combo_surf = combo_base
                shadow_surf = shadow_base
            if tip_pos is not None:
                cx = int(tip_pos[0]) + 30 - combo_surf.get_width() // 2
                cy = int(tip_pos[1]) - 70 - combo_surf.get_height() // 2
            else:
                cx = self._w // 2 - combo_surf.get_width() // 2
                cy = self._h // 2 - 60
            screen.blit(shadow_surf, (cx + 3, cy + 3))
            screen.blit(combo_surf, (cx, cy))
        else:
            self._prev_combo = 0
            self._combo_pop_end_ms = 0

    # ------------------------------------------------------------------ helpers

    def _dim(self, alpha: int = 160) -> None:
        overlay = pygame.Surface((self._w, self._h), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, alpha))
        self._screen.blit(overlay, (0, 0))

    def _center_text(self, font: pygame.font.Font, text: str, y: int, color=WHITE) -> None:
        surf = font.render(text, True, color)
        self._screen.blit(surf, (self._w // 2 - surf.get_width() // 2, y))

    def _center_text_shadow(self, font: pygame.font.Font, text: str, y: int, color=WHITE) -> None:
        shadow = font.render(text, True, (0, 0, 0))
        surf = font.render(text, True, color)
        cx = self._w // 2 - surf.get_width() // 2
        self._screen.blit(shadow, (cx + 4, y + 4))
        self._screen.blit(surf, (cx, y))

    def _outlined_text(self, font: pygame.font.Font, text: str, x: int, y: int,
                       main_color, outline_color=(0, 0, 0), outline_px: int = 3) -> None:
        outline = font.render(text, True, outline_color)
        for dx, dy in [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]:
            self._screen.blit(outline, (x + dx * outline_px, y + dy * outline_px))
        self._screen.blit(font.render(text, True, main_color), (x, y))

    def _outlined_text_centered(self, font: pygame.font.Font, text: str, y: int,
                                main_color, outline_color=(0, 0, 0), outline_px: int = 3) -> int:
        w, h = font.size(text)
        self._outlined_text(font, text, self._w // 2 - w // 2, y, main_color, outline_color, outline_px)
        return h

    def _banner_top(self, text: str, color) -> None:
        surf = self._font_hud.render(text, True, WHITE)
        pad = 14
        rect = pygame.Rect(
            self._w // 2 - surf.get_width() // 2 - pad, 100, surf.get_width() + 2 * pad, surf.get_height() + pad
        )
        pygame.draw.rect(self._screen, color, rect, border_radius=8)
        self._screen.blit(surf, (rect.x + pad, rect.y + pad // 2))

    # ------------------------------------------------------------------ phases

    # Faint background slash decorations — fixed positions, drawn each idle frame
    _BG_SLASHES = [
        (0.06, 0.18, 0.20, 0.52),
        (0.74, 0.04, 0.90, 0.44),
        (0.40, 0.62, 0.54, 0.94),
        (0.14, 0.70, 0.27, 0.97),
        (0.62, 0.58, 0.78, 0.92),
        (0.30, 0.08, 0.44, 0.38),
    ]

    def _draw_idle(self, menu_cursor: int = 0, dt: float = 0.0) -> None:
        ticks = pygame.time.get_ticks()
        self._dim(158)

        # Drifting background fruits
        self._update_bg_fruits(dt)
        self._draw_bg_fruits()

        # Faint diagonal slash marks for atmosphere
        for x1f, y1f, x2f, y2f in self._BG_SLASHES:
            pygame.draw.line(
                self._screen, (150, 25, 25),
                (int(x1f * self._w), int(y1f * self._h)),
                (int(x2f * self._w), int(y2f * self._h)), 1,
            )

        SLASH_RED = (210, 30, 30)
        ORANGE    = (255, 140, 0)

        # ── Title (top) ──────────────────────────────────────────────────────
        ty = 22
        title_h = self._outlined_text_centered(
            self._font_title, "SLICE  RUSH", ty, (255, 255, 255), SLASH_RED, 4
        )
        tw, _ = self._font_title.size("SLICE  RUSH")
        lx1 = self._w // 2 - tw // 2 - 24
        lx2 = self._w // 2 + tw // 2 + 24
        line_y = ty + title_h + 4
        pygame.draw.line(self._screen, SLASH_RED, (lx1, line_y), (lx2, line_y), 3)
        pygame.draw.circle(self._screen, ORANGE, (lx1, line_y), 4)
        pygame.draw.circle(self._screen, ORANGE, (lx2, line_y), 4)

        pulse = 0.5 + 0.5 * math.sin(ticks / 700)
        sub_color = (int(190 + 40 * pulse), int(45 + 15 * pulse), int(45 + 15 * pulse))
        sub_surf = self._font_hud.render("SLICE  ·  DICE  ·  SURVIVE", True, sub_color)
        sub_surf.set_alpha(int(130 + 80 * pulse))
        sub_y = line_y + 8
        self._screen.blit(sub_surf, (self._w // 2 - sub_surf.get_width() // 2, sub_y))

        # ── Leaderboard (middle) ─────────────────────────────────────────────
        LB_TOP = sub_y + sub_surf.get_height() + 18
        ROW_H  = 68   # sized for _font_lb (62px)

        hdr = self._font_lb.render("HIGH SCORES", True, SLASH_RED)
        self._screen.blit(hdr, (self._w // 2 - hdr.get_width() // 2, LB_TOP))
        div_y = LB_TOP + hdr.get_height() + 6
        pygame.draw.line(self._screen, SLASH_RED,
                         (self._w // 2 - 160, div_y), (self._w // 2 + 160, div_y), 2)

        if self.leaderboard_rows:
            for rank, row in enumerate(self.leaderboard_rows[:3], start=1):
                ry = div_y + 8 + (rank - 1) * ROW_H
                color = RANK_COLORS[rank - 1]
                entry = self._font_lb.render(
                    f"#{rank}  {row.player_name:<12}  {row.final_score} pts",
                    True, color,
                )
                self._screen.blit(entry, (self._w // 2 - entry.get_width() // 2, ry))
            lb_end_y = div_y + 8 + 3 * ROW_H
        else:
            empty = self._font_lb.render("No scores yet — be the first!", True, (130, 130, 145))
            self._screen.blit(empty, (self._w // 2 - empty.get_width() // 2, div_y + 8))
            lb_end_y = div_y + 8 + hdr.get_height()

        # ── Menu items (bottom) ──────────────────────────────────────────────
        # ITEM_Y is derived from where the leaderboard ends, so sections never overlap.
        HINT_Y  = self._h - 36
        SPACING = 56
        ITEM_Y  = lb_end_y + 18

        LABELS = ["START GAME", "SETTINGS", "EXIT"]
        slash_surf = self._font_menu.render("/", True, ORANGE)
        slash_flip = pygame.transform.flip(slash_surf, True, False)

        for i, label in enumerate(LABELS):
            y = ITEM_Y + i * SPACING
            iw, ih = self._font_menu.size(label)
            cx = self._w // 2 - iw // 2

            if i == menu_cursor:
                pm = 0.5 + 0.5 * math.sin(ticks / 320)
                bg_col   = (int(200 + 30 * pm), int(40 * pm), 0)
                bg_alpha = int(55 + 35 * pm)
                backing  = pygame.Surface((iw + 60, ih + 10), pygame.SRCALPHA)
                backing.fill((*bg_col, bg_alpha))
                bx = self._w // 2 - backing.get_width() // 2
                self._screen.blit(backing, (bx, y - 5))
                self._outlined_text(self._font_menu, label, cx, y, (255, 255, 255), (0, 0, 0), 2)
                self._screen.blit(slash_surf, (bx - slash_surf.get_width() - 2, y))
                self._screen.blit(slash_flip,  (bx + backing.get_width() + 2,  y))
            else:
                self._outlined_text(self._font_menu, label, cx, y, (155, 155, 170), (0, 0, 0), 1)

        # ── Navigation hint ──────────────────────────────────────────────────
        hint = self._font_board.render("↑ ↓  navigate    ENTER  select", True, (78, 78, 90))
        self._screen.blit(hint, (self._w // 2 - hint.get_width() // 2, HINT_Y))

    def _draw_countdown(self, state: GameStateMachine) -> None:
        remaining = state.countdown_timer
        label = "GO!" if remaining <= 0 else str(int(remaining) + 1)
        frac = remaining - int(remaining)
        scale = 1.0 + 0.35 * frac
        ticks = pygame.time.get_ticks()
        hue = (ticks // 6) % 360
        color = _hsv_color(hue, 80, 100) if remaining <= 0 else (255, 235, 70)
        text = self._font_countdown.render(label, True, color)
        shadow = self._font_countdown.render(label, True, (0, 0, 0))
        text = pygame.transform.rotozoom(text, 0, scale)
        shadow = pygame.transform.rotozoom(shadow, 0, scale)
        cx = self._w // 2 - text.get_width() // 2
        cy = self._h // 2 - text.get_height() // 2
        self._screen.blit(shadow, (cx + 6, cy + 6))
        self._screen.blit(text, (cx, cy))

    def _draw_round_transition(self, state: GameStateMachine) -> None:
        cfg_time = self._config.game.timers.round_transition_seconds
        elapsed = cfg_time - state.transition_timer
        pop_t = min(1.0, elapsed / 0.35)
        scale = 2.0 - pop_t  # 2.0 → 1.0 in first 0.35 s, then holds at 1.0

        label = f"ROUND {state.round_number - 1} CLEAR!"
        banner = self._font_banner.render(label, True, (120, 240, 120))
        shadow = self._font_banner.render(label, True, (0, 0, 0))
        banner = pygame.transform.rotozoom(banner, 0, max(1.0, scale))
        shadow = pygame.transform.rotozoom(shadow, 0, max(1.0, scale))
        bx = self._w // 2 - banner.get_width() // 2
        by = self._h // 2 - banner.get_height() // 2 - 60
        self._screen.blit(shadow, (bx + 5, by + 5))
        self._screen.blit(banner, (bx, by))

        sub = self._font_hud.render(f"Next target: {state.current_round_target()} pts", True, (200, 200, 200))
        self._screen.blit(sub, (self._w // 2 - sub.get_width() // 2, by + banner.get_height() + 16))

    def _draw_game_over(self, state: GameStateMachine) -> None:
        self._dim(175)
        ticks = pygame.time.get_ticks()
        pulse = 0.5 + 0.5 * math.sin(ticks / 350)
        red = (int(210 + 45 * pulse), int(30 + 20 * pulse), int(30 + 20 * pulse))
        self._center_text_shadow(self._font_banner, "GAME OVER", self._h // 2 - 180, red)

        # Stats panel
        panel_w, panel_h = 500, 180
        px = self._w // 2 - panel_w // 2
        py = self._h // 2 - 60
        panel = pygame.Surface((panel_w, panel_h), pygame.SRCALPHA)
        panel.fill((0, 0, 0, 120))
        self._screen.blit(panel, (px, py))

        self._center_text(self._font_hud, f"Final score:  {state.score}", py + 24, (255, 235, 70))
        self._center_text(self._font_hud, f"Rounds reached:  {state.round_number}", py + 72, WHITE)
        self._center_text(self._font_hud, f"Best combo:  x{state.max_combo}", py + 120, (200, 200, 255))

    def _draw_score_submit(self, state: GameStateMachine, name_buffer: str) -> None:
        self._dim()
        if self._config.persistence.name_entry:
            self._center_text_shadow(self._font_banner, f"{state.score} pts", self._h // 2 - 210, (255, 235, 70))
            self._center_text(self._font_hud, f"Enter name: {name_buffer}_", self._h // 2 - 40)
            self._center_text(self._font_hud, "Press ENTER to save", self._h // 2 + 20)
            self._center_text(
                self._font_board,
                f"auto-saving in {max(0, int(state.submit_timer))}s",
                self._h // 2 + 72,
                (160, 160, 160),
            )
        else:
            self._center_text_shadow(self._font_banner, "Score saved!", self._h // 2 - 60, (120, 230, 120))

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
