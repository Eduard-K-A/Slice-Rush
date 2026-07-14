# Slice Rush — "Fruit Ninja" Booth Game

A camera-tracked motion game for the Enlistment Week booth: players swing an
LED-tipped stick in front of a USB camera to slice fruit falling across a live
mirrored video feed of themselves. Rounds last 10 seconds with escalating
score targets (40, 80, 120, 160, …), 3 hearts, combos, and a persistent
leaderboard shown between players.

Built per `docs/SLICE_RUSH_IMPLEMENTATION_PLAN.md` (v2.0) from
`docs/Slice_Rush_Fruit_Ninja_PRD.md`.

- **Platform:** Windows 10/11 laptop + **external USB camera** (DirectShow) + TV over HDMI
- **Stack:** Python 3.11+, OpenCV, NumPy, Pygame, SQLite (no server, no ML models)

---

## Quick start

```powershell
# 1. Create the environment (Python 3.11+; 3.11 recommended)
py -3.11 -m venv venv
.\venv\Scripts\Activate.ps1 # or "source venv/Scripts/activate"     for bash terminal
pip install -r requirements.txt

# 2. (Only if assets/ is empty — generated art & sounds are committed)
python -m src.tools.generate_sprites
python -m src.tools.generate_sounds

# 3. Find your external USB camera's index (usually 1 on laptops)
python -m src.tools.list_cameras
#    -> set camera.device_index in config/config.yaml

# 4. Verify the feed (mirrored, fps, exposure accepted)
python -m src.tools.test_capture        # q quits

# 5. Calibrate the LED color under YOUR lighting (required before first play)
python -m src.tools.calibrate

# 6. Play
python -m src.main
```

## Controls (volunteer keys)

| Key | Action |
|---|---|
| `SPACE` | Start a new game (from the leaderboard/attract screen) |
| `R` | Abort the current game and return to the attract screen (no score saved) |
| `F1` | Toggle the operator debug overlay (HSV mask, fps, tip speed/lost state) |
| `ESC` | Quit |
| typing + `ENTER` | Player name entry on the score screen (auto-saves as "Player" after 20 s) |

## Game rules

- Fruits fall from the top of the screen; slice them by swinging the LED stick.
- Points: apple / banana / strawberry **10**, pineapple **15**, watermelon **20**.
- Each round lasts **10 seconds**. When the timer expires you advance only if
  your **cumulative** score has reached the round target (40, 80, 120, 160, …);
  otherwise the game ends.
- You have **3 hearts**. Slicing a **bomb or rock** costs 1 heart and resets
  your combo. At 0 hearts the game ends immediately.
- **Missing** a fruit only resets your combo — it never costs a heart.
- Difficulty scales every round: faster spawns, more bombs/rocks (both capped
  so late rounds stay playable).
- The stick tip must be **moving** to slice (default ≥ 350 px/s) — resting the
  stick on the screen does nothing.

---

## Hardware setup

### The stick

- A stick with a **colored LED at the tip**, covered by a diffuser (a cut
  ping-pong ball works well) for a soft, evenly lit blob.
- Pick an LED color that doesn't appear in your booth backdrop or typical
  clothing — saturated magenta/pink survives most environments. The final
  check is `calibrate.py` under real booth lighting.
- Battery + switch in the handle; keep spares at the booth. Use a lightweight,
  soft-tipped or tethered stick with clear swing space (public safety).

### The camera (external USB, Windows)

- Plug **directly** into the laptop (no unpowered hub); tape the cable down.
- Windows can renumber cameras after replug/reboot — re-run
  `python -m src.tools.list_cameras` and re-check `camera.device_index`
  every time you set up.
- Close everything else that can grab the camera (Teams, Zoom, browser tabs,
  Windows Camera app) — DirectShow cannot open a busy device.
- Windows Settings → Privacy & security → Camera → allow desktop apps.
- Power plan "High performance", disable USB selective suspend and sleep;
  laptop on AC power. TV duplicated over HDMI at 720p/1080p.
- **Exposure and white balance must be locked** before saving HSV values, or
  detection drifts as the crowd changes scene brightness. `capture.py` locks
  them programmatically; if your driver ignores that (it's logged at startup),
  press `d` inside `calibrate.py` to open the driver dialog and lock manually.

### Opening-day sequence (~15 min)

`list_cameras` → set index → `test_capture` (verify fps + mirroring) →
`calibrate` (lock exposure/WB with `e`/`d`, tune HSV, `s` to save) →
`python -m src.main` → one volunteer test run → open the line.

---

## Calibration tool

`python -m src.tools.calibrate` opens the live feed plus the exact binary
mask the game will see (same blur/morphology pipeline).

| Key | Action |
|---|---|
| `t` / `h` | Edit the `tip` / optional `handle` marker |
| trackbars | H/S/V min–max bounds; the mask window updates live |
| `e` | Cycle exposure presets (-5 / -7 / -9) |
| `d` | Open the DirectShow driver settings dialog (manual exposure/WB lock) |
| `s` | Save the edited marker's HSV bounds + current exposure to `config/config.yaml` |
| `q` | Quit without saving |

Goal: the mask shows **one clean white blob** at the LED tip and nothing
else, across the whole play area. Re-run whenever the lighting changes
(e.g. day vs. evening).

---

## Configuration

Everything lives in `config/config.yaml`. Highlights:

| Key | Meaning |
|---|---|
| `camera.device_index` | Which camera to open — from `list_cameras` |
| `camera.exposure_value` | Manual exposure (DSHOW log2 seconds, e.g. -7 ≈ 1/128 s) |
| `detection.markers[].hsv_lower/upper` | LED color bounds — set by `calibrate.py` |
| `game.difficulty.*` | Spawn rate / bomb ratio curves (playtest knobs) |
| `game.physics.*` | Gravity, fall speeds, drift, spin |
| `game.slice.min_speed_px_s` | Minimum tip speed to register a slice |
| `game.scoring.fruit_points` | Per-fruit point values |
| `display.fullscreen` | `false` for windowed testing |
| `audio.enabled` | `false` for a silent booth |
| `persistence.name_entry` | `false` to skip the name screen (saves as "Player") |

Missing `camera`/`detection`/`persistence` keys fail fast at startup with the
key named; gameplay keys fall back to safe defaults (logged).

## Artwork & sounds

All sprites (whole fruit + sliced halves, bomb, rock) and sound effects are
**generated deterministically** by:

```powershell
python -m src.tools.generate_sprites   # -> assets/sprites/*.png (256x256 RGBA)
python -m src.tools.generate_sounds    # -> assets/sounds/*.wav  (44.1 kHz mono)
```

Want nicer art? Drop replacement PNGs into `assets/sprites/` using the same
filenames (`apple.png`, `apple_half_1.png`, `apple_half_2.png`, …,
`bomb.png`, `rock.png`) — no code changes needed. Use **CC0/public-domain
art only** (e.g. [kenney.nl](https://kenney.nl),
[opengameart.org](https://opengameart.org)) and record the source in
`assets/CREDITS.md`. A `.ttf` dropped into `assets/fonts/` is picked up
automatically for all UI text.

## Leaderboard data

Sessions are stored in `data/slice_rush.db` (SQLite, created automatically):
player name, final score, rounds reached, hearts remaining, max combo,
timestamp. The attract screen shows the top 10. Delete the file to reset the
leaderboard for a new event day.

---

## Development

### Project layout

```
src/
  main.py               orchestration + main loop (60 fps render / camera-rate vision)
  config_loader.py      YAML -> typed dataclasses, fail-fast on hardware keys
  vision/
    capture.py          threaded DirectShow capture, exposure/WB lock, auto-reconnect
    detection.py        HSV blob detection (blur -> inRange -> morphology -> contours)
    tracking.py         constant-velocity Kalman filter (plain NumPy)
  game/
    entities.py         spawn system + gravity/tumble physics
    slice_logic.py      tip trail + segment-vs-circle collision
    difficulty.py       round target / spawn interval / bad-object ratio formulas
    game_state.py       phase state machine (all timers dt-driven, fully testable)
    effects.py          flying halves, juice particles, popups, shake, red flash
    audio.py            pygame.mixer wrapper (silent no-op on any failure)
    renderer.py         camera feed + sprites + HUD + phase overlays + debug view
  persistence/
    db.py               SQLite connection + schema
    leaderboard.py      insert/top-N repository (write failures never crash the booth)
  tools/
    list_cameras.py     find the external camera's index
    test_capture.py     live capture smoke test
    calibrate.py        HSV/exposure calibration UI
    generate_sprites.py / generate_sounds.py   deterministic asset generators
tests/                  58 hardware-independent unit tests
```

### Tests

```powershell
.\venv\Scripts\python.exe -m pytest tests/ -v
```

All tests run without a camera or display (synthetic frames, seeded RNGs,
SDL dummy video driver) — safe for CI.

### Troubleshooting

| Symptom | Fix |
|---|---|
| "Camera failed to open" screen | Wrong index (run `list_cameras`), busy device (close Teams/Zoom), or Windows camera privacy blocking desktop apps |
| Game runs but nothing slices | Run `calibrate.py` — the mask window must show the LED as one clean blob. Check `F1` overlay: "tip lost: True" means detection isn't finding the marker |
| Slices trigger without moving | Raise `game.slice.min_speed_px_s` |
| Detection drifts over the day | Exposure/white balance not locked — check startup logs, use `d` in `calibrate.py`, re-save HSV |
| Choppy video | Camera negotiated a low fps — confirm `MJPG` was accepted in the startup logs; try a different USB port |
| "CAMERA DISCONNECTED" banner | USB cable dropped — the round timer pauses and the game auto-reconnects on replug |
| Low fps / stutter overall | High-performance power plan, plug in AC, close background apps |
