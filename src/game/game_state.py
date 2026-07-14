"""Game state machine (State pattern — explicit enum-driven transitions).

All timers are driven exclusively by the dt argument to tick(): no
wall-clock reads inside this class, so every transition is unit-testable.
"""
from __future__ import annotations

from enum import Enum

from src.config_loader import GameConfig
from src.game.difficulty import round_target
from src.persistence.db import SessionRecord


class GamePhase(Enum):
    IDLE_ATTRACT = "idle_attract"
    COUNTDOWN = "countdown"
    PLAYING = "playing"
    ROUND_TRANSITION = "round_transition"
    GAME_OVER = "game_over"
    SCORE_SUBMIT = "score_submit"


class GameStateMachine:
    def __init__(self, config: GameConfig):
        self._config = config
        self.phase = GamePhase.IDLE_ATTRACT
        self.score = 0
        self.hearts = config.starting_hearts
        self.round_number = 1
        self.combo = 0
        self.max_combo = 0
        self.round_timer = 0.0
        self.countdown_timer = 0.0
        self.transition_timer = 0.0
        self.game_over_timer = 0.0
        self.submit_timer = 0.0
        self._timer_paused = False

    # ------------------------------------------------------------------ commands

    def start_new_game(self) -> None:
        self.score = 0
        self.hearts = self._config.starting_hearts
        self.round_number = 1
        self.combo = 0
        self.max_combo = 0
        self.round_timer = self._config.timers.round_duration_seconds
        self.countdown_timer = self._config.timers.countdown_seconds
        self.phase = GamePhase.COUNTDOWN

    def register_fruit_hit(self, points: int) -> None:
        if self.phase not in (GamePhase.PLAYING, GamePhase.ROUND_TRANSITION):
            return
        self.combo += 1
        self.max_combo = max(self.max_combo, self.combo)
        self.score += points
        combo_cfg = self._config.combo
        if combo_cfg.combo_bonus_points > 0 and self.combo % combo_cfg.combo_bonus_threshold == 0:
            self.score += combo_cfg.combo_bonus_points

    def register_bad_hit(self) -> None:
        if self.phase not in (GamePhase.PLAYING, GamePhase.ROUND_TRANSITION):
            return
        self.hearts -= 1
        self.combo = 0
        if self.hearts <= 0:
            self.hearts = 0
            self._enter_game_over()

    def register_miss(self) -> None:
        # Missing a fruit only resets the combo — never costs a heart (A3).
        if self.phase not in (GamePhase.PLAYING, GamePhase.ROUND_TRANSITION):
            return
        self.combo = 0

    def set_timer_paused(self, paused: bool) -> None:
        self._timer_paused = paused

    def current_round_target(self) -> int:
        return round_target(
            self.round_number, self._config.score_target.base, self._config.score_target.increment
        )

    # ------------------------------------------------------------------ tick

    def tick(self, dt: float) -> None:
        if self.phase is GamePhase.COUNTDOWN:
            self.countdown_timer -= dt
            if self.countdown_timer <= 0:
                self.phase = GamePhase.PLAYING
                self.round_timer = self._config.timers.round_duration_seconds
        elif self.phase is GamePhase.PLAYING:
            if not self._timer_paused:
                self.round_timer -= dt
                if self.round_timer <= 0:
                    # Timer always runs the full round (A2); evaluate only here.
                    if self.score >= self.current_round_target():
                        self.round_number += 1
                        self.transition_timer = self._config.timers.round_transition_seconds
                        self.phase = GamePhase.ROUND_TRANSITION
                    else:
                        self._enter_game_over()
        elif self.phase is GamePhase.ROUND_TRANSITION:
            self.transition_timer -= dt
            if self.transition_timer <= 0:
                self.phase = GamePhase.PLAYING
                self.round_timer = self._config.timers.round_duration_seconds
        elif self.phase is GamePhase.GAME_OVER:
            self.game_over_timer -= dt
            if self.game_over_timer <= 0:
                self.phase = GamePhase.SCORE_SUBMIT
                self.submit_timer = self._config.timers.score_submit_timeout_seconds
        elif self.phase is GamePhase.SCORE_SUBMIT:
            self.submit_timer -= dt
            # main watches submit_timer <= 0 and calls finalize_session.

    # ------------------------------------------------------------------ terminal transitions

    def _enter_game_over(self) -> None:
        self.game_over_timer = self._config.timers.game_over_seconds
        self.phase = GamePhase.GAME_OVER

    def finalize_session(self, player_name: str) -> SessionRecord:
        """Called by main exactly once per game. Returns the record and
        returns the machine to IDLE_ATTRACT."""
        record = SessionRecord(
            player_name=player_name or "Player",
            final_score=self.score,
            rounds_reached=self.round_number,
            hearts_remaining=self.hearts,
            max_combo=self.max_combo,
        )
        self.phase = GamePhase.IDLE_ATTRACT
        return record

    def abort_to_idle(self) -> None:
        """R key or idle timeout — abandoned runs are not scores."""
        self.phase = GamePhase.IDLE_ATTRACT
