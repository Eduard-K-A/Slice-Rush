from src.config_loader import ComboConfig, GameConfig
from src.game.game_state import GamePhase, GameStateMachine


def make_state(**overrides):
    cfg = GameConfig(**overrides)
    sm = GameStateMachine(cfg)
    return sm, cfg


def start_playing(sm, cfg):
    sm.start_new_game()
    sm.tick(cfg.timers.countdown_seconds + 0.01)
    assert sm.phase is GamePhase.PLAYING
    return sm


def test_start_new_game_resets():
    sm, cfg = make_state()
    sm.start_new_game()
    assert sm.phase is GamePhase.COUNTDOWN
    assert (sm.score, sm.hearts, sm.round_number, sm.combo, sm.max_combo) == (0, 3, 1, 0, 0)


def test_round_advances_immediately_when_target_met():
    sm, cfg = make_state()
    start_playing(sm, cfg)
    for _ in range(4):
        sm.register_fruit_hit(10)  # 40 pts = round 1 target — advances without waiting for timer
    assert sm.phase is GamePhase.ROUND_TRANSITION
    assert sm.round_number == 2
    sm.tick(cfg.timers.round_transition_seconds + 0.01)
    assert sm.phase is GamePhase.PLAYING
    assert sm.round_timer == cfg.timers.round_duration_seconds


def test_game_over_when_target_missed_at_expiry():
    sm, cfg = make_state()
    start_playing(sm, cfg)
    sm.register_fruit_hit(10)  # 10 < 40
    sm.tick(cfg.timers.round_duration_seconds + 0.01)
    assert sm.phase is GamePhase.GAME_OVER


def test_round_does_not_advance_mid_round_below_target():
    sm, cfg = make_state()
    start_playing(sm, cfg)
    for _ in range(3):
        sm.register_fruit_hit(10)  # 30 < 40 target
    sm.tick(1.0)
    assert sm.phase is GamePhase.PLAYING


def test_immediate_game_over_at_zero_hearts_mid_round():
    sm, cfg = make_state()
    start_playing(sm, cfg)
    for _ in range(3):
        sm.register_bad_hit()
    assert sm.hearts == 0
    assert sm.phase is GamePhase.GAME_OVER


def test_combo_resets_on_bad_hit_and_miss_but_not_fruit():
    sm, cfg = make_state()
    start_playing(sm, cfg)
    sm.register_fruit_hit(10)
    sm.register_fruit_hit(10)
    assert sm.combo == 2
    sm.register_miss()
    assert sm.combo == 0
    sm.register_fruit_hit(10)
    sm.register_bad_hit()
    assert sm.combo == 0
    assert sm.max_combo == 2


def test_miss_never_costs_heart():
    sm, cfg = make_state()
    start_playing(sm, cfg)
    for _ in range(10):
        sm.register_miss()
    assert sm.hearts == cfg.starting_hearts


def test_combo_bonus_when_enabled():
    sm, cfg = make_state(combo=ComboConfig(combo_bonus_threshold=2, combo_bonus_points=5))
    start_playing(sm, cfg)
    sm.register_fruit_hit(10)  # combo 1: 10
    sm.register_fruit_hit(10)  # combo 2: 10 + 5 bonus
    assert sm.score == 25


def test_game_over_to_submit_to_idle_flow():
    sm, cfg = make_state()
    start_playing(sm, cfg)
    sm.tick(cfg.timers.round_duration_seconds + 0.01)  # target missed
    assert sm.phase is GamePhase.GAME_OVER
    sm.tick(cfg.timers.game_over_seconds + 0.01)
    assert sm.phase is GamePhase.SCORE_SUBMIT
    assert sm.submit_timer > 0
    record = sm.finalize_session("Ed")
    assert record.player_name == "Ed"
    assert sm.phase is GamePhase.IDLE_ATTRACT


def test_finalize_empty_name_defaults_player():
    sm, cfg = make_state()
    start_playing(sm, cfg)
    sm.register_bad_hit(); sm.register_bad_hit(); sm.register_bad_hit()
    sm.tick(cfg.timers.game_over_seconds + 0.01)
    record = sm.finalize_session("")
    assert record.player_name == "Player"
    assert record.hearts_remaining == 0


def test_timer_pause_freezes_round_timer():
    sm, cfg = make_state()
    start_playing(sm, cfg)
    sm.set_timer_paused(True)
    before = sm.round_timer
    sm.tick(5.0)
    assert sm.round_timer == before
    assert sm.phase is GamePhase.PLAYING
    sm.set_timer_paused(False)
    sm.tick(0.5)
    assert sm.round_timer < before


def test_abort_to_idle():
    sm, cfg = make_state()
    start_playing(sm, cfg)
    sm.abort_to_idle()
    assert sm.phase is GamePhase.IDLE_ATTRACT


def test_register_calls_ignored_outside_play():
    sm, cfg = make_state()
    sm.register_fruit_hit(10)
    sm.register_bad_hit()
    sm.register_miss()
    assert sm.score == 0
    assert sm.hearts == cfg.starting_hearts
