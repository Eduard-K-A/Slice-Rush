# Slice Rush — "Fruit Ninja" Booth Game

A camera-tracked motion game for the Enlistment Week booth: players slice
fruit falling across the screen using either an **LED-tipped stick** (HSV color
detection) or their **bare index finger** (MediaPipe hand tracking). Rounds
last 10 seconds with escalating score targets (40, 80, 120, 160, …), 3 hearts,
combos with heart restoration, and a persistent leaderboard shown between
players.

- **Platform:** Windows 10/11 laptop + external USB camera (DirectShow) + TV over HDMI
- **Stack:** Python 3.11+, OpenCV, MediaPipe, NumPy, Pygame, SQLite

---

## Quick start

```powershell
# 1. Create the environment (Python 3.11+; 3.11 recommended)
py -3.11 -m venv venv
.\venv\Scripts\Activate.ps1       # or: source venv/Scripts/activate (bash)
pip install -r requirements.txt

# 2. (Only if assets/ is empty — generated art & sounds are committed)
python -m src.tools.generate_sprites
python -m src.tools.generate_sounds

# 3. Run — everything else is configured from inside the game
python -m src.main
```

Camera selection, detection mode, HSV calibration, and window mode are all
accessible from the **Settings** screen inside the main menu. No need to run
separate scripts.

---

## Main menu

The game opens to a fruit-ninja-themed main menu with three options:

| Option | Action |
|---|---|
| **Start Game** | Begin a new game immediately |
| **Settings** | Open the in-game settings screen |
| **Exit** | Quit the application |

Navigate with `↑` / `↓` and confirm with `ENTER`.

---

## Settings screen

Press `ENTER` on **Settings** from the main menu. Navigate rows with `↑` / `↓`,
change values with `←` / `→`, and press `ENTER` on **Back** (or `ESC`) to save
and return.

| Setting | Options |
|---|---|
| **Camera Index** | 0 – 5 (available cameras shown in green, unavailable in red) |
| **Detection Mode** | `HSV` (LED stick) · `Hand` (bare index finger via MediaPipe) |
| **Color Preset** | White/Bright · Neon Green · Bright Yellow · Pink/Magenta · Blue · Red |
| **Window Mode** | Fullscreen (borderless) · Windowed |
| **Fine-tune Calibration** | Opens the live HSV calibration tool |
| **Back** | Save all changes to `config/config.yaml` and return |

Color Preset is only active in **HSV** mode.

---

## Controls

| Key | Action |
|---|---|
| `↑` / `↓` | Navigate menu / settings items |
| `←` / `→` | Change selected setting value |
| `ENTER` | Confirm selection |
| `ESC` | Return to previous screen / quit from main menu |
| `R` | Abort the current game and return to menu (no score saved) |
| `F1` | Toggle the operator debug overlay (HSV mask, fps, tip speed) |
| typing + `ENTER` | Player name entry on the score screen |

---

## Game rules

- Fruits fall from the top; slice them by moving the LED stick or your index
  finger across them at speed.
- **Points:** apple / banana / strawberry **10 pts**, pineapple **15 pts**,
  watermelon **20 pts**.
- Each round lasts **10 seconds**. Advance only if your **cumulative** score
  has reached the round target (40, 80, 120, 160, …); otherwise the game ends.
- You have **3 hearts**. Slicing a **bomb or rock** costs 1 heart and resets
  your combo. At 0 hearts the game ends immediately.
- **Missing** a fruit only resets your combo — it never costs a heart.
- **Combo heart restore:** every time your combo reaches a multiple of **8**,
  you regain 1 lost heart (up to the 3-heart maximum). A `+1 ♥` popup
  appears at the slice position.
- **Difficulty scales** each round: entities fall faster and more bombs/rocks
  spawn (both capped so late rounds stay playable).

---

## Detection modes

### HSV (LED stick)

The original mode. An LED-tipped stick covered by a diffuser (ping-pong ball)
produces a soft colored blob that OpenCV tracks via HSV thresholding.

- Use a color that doesn't appear in your backdrop or typical clothing —
  saturated magenta/pink or bright yellow works well under most lighting.
- Calibrate HSV bounds from **Settings → Fine-tune Calibration** or by running
  `python -m src.tools.calibrate` directly.
- Lock camera exposure and white balance before saving HSV values, or detection
  drifts as crowd density changes scene brightness.

### Hand (index finger, MediaPipe)

Tracks the **index fingertip** (landmark 8) using the MediaPipe HandLandmarker
model. No stick or calibration required — works under normal lighting.

- The model file (`hand_landmarker.task`, ~9 MB) is downloaded automatically
  on first use to `assets/models/`.
- An orange circle and skeleton overlay are drawn on the camera feed to show
  the active tracking point.
- Works best with good ambient lighting and a plain background behind the hand.

---

## Hardware setup

### Camera

- Plug the USB camera **directly** into the laptop (no unpowered hub); tape
  the cable down.
- Windows can renumber cameras after replug/reboot — re-check the index in
  **Settings** if the feed fails to open.
- Close anything else that can grab the camera (Teams, Zoom, browser tabs,
  Windows Camera app) — DirectShow cannot open a busy device.
- Windows Settings → Privacy & security → Camera → allow desktop apps.
- Power plan "High performance", disable USB selective suspend; laptop on AC
  power. Duplicate display to TV at 720p/1080p over HDMI.

### LED stick (HSV mode only)

- Battery + switch in the handle; keep spares at the booth.
- Use a lightweight, soft-tipped or tethered stick with clear swing space.

### Opening-day sequence (~10 min)

1. Launch `python -m src.main`.
2. Open **Settings** → set Camera Index to the external camera.
3. Choose Detection Mode (`HSV` or `Hand`).
4. If HSV: select a Color Preset close to your LED, then open
   **Fine-tune Calibration** to dial it in under booth lighting.
5. Press `Back` to save, then **Start Game** for a volunteer test run.

---

## Configuration

Everything lives in `config/config.yaml`. The settings screen writes back to
this file automatically. Manual highlights:

| Key | Meaning |
|---|---|
| `camera.device_index` | Which camera to open |
| `camera.exposure_value` | Manual exposure (DSHOW log2 seconds, e.g. `-7` ≈ 1/128 s) |
| `detection_mode` | `hsv` or `hand` |
| `hand_detection.landmark_index` | MediaPipe landmark to track (default `8` = index fingertip) |
| `detection.markers[].hsv_lower/upper` | LED color bounds — set by calibration tool |
| `display.fullscreen` | `true` for borderless fullscreen, `false` for windowed |
| `game.difficulty.*` | Spawn rate / bomb ratio curves |
| `game.physics.*` | Gravity, fall speeds, drift, spin, per-round scale |
| `game.slice.min_speed_px_s` | Minimum tip speed to register a slice |
| `game.scoring.fruit_points` | Per-fruit point values |
| `audio.enabled` | `false` for a silent booth |
| `persistence.name_entry` | `false` to skip the name screen (saves as "Player") |

Missing `camera`/`persistence` keys fail fast at startup with the key named;
gameplay keys fall back to safe defaults (logged).

---

## Artwork & sounds

All sprites and sound effects are **generated deterministically**:

```powershell
python -m src.tools.generate_sprites   # -> assets/sprites/*.png (RGBA)
python -m src.tools.generate_sounds    # -> assets/sounds/*.wav  (44.1 kHz mono)
```

Drop replacement PNGs into `assets/sprites/` using the same filenames
(`apple.png`, `apple_half_1.png`, `apple_half_2.png`, …, `bomb.png`,
`rock.png`) — no code changes needed. A `.ttf` dropped into `assets/fonts/`
is picked up automatically for all UI text (the game ships with
**Bangers-Regular.ttf**). Use CC0/public-domain art only (e.g.
[kenney.nl](https://kenney.nl), [opengameart.org](https://opengameart.org))
and record the source in `assets/CREDITS.md`.

---

## Leaderboard data

Sessions are stored in `data/slice_rush.db` (SQLite, created automatically):
player name, final score, rounds reached, hearts remaining, max combo,
timestamp. The main menu shows the top 3 scores. Delete the file to reset the
leaderboard for a new event day.

---

## Development

### Project layout

```
src/
  main.py               main loop, settings screen, keyboard routing (sole entry point)
  config_loader.py      YAML -> typed dataclasses; save_config() for partial updates
  vision/
    capture.py          threaded DirectShow capture, exposure/WB lock, auto-reconnect
    detection.py        HSV blob detector + MediaPipe hand landmarker (HandDetector)
    tracking.py         constant-velocity Kalman filter (plain NumPy)
  game/
    entities.py         spawn system + gravity/tumble physics + per-round speed scale
    slice_logic.py      tip trail + segment-vs-circle collision
    difficulty.py       round target / spawn interval / bad-object ratio formulas
    game_state.py       phase state machine (IDLE_ATTRACT, SETTINGS_MENU, COUNTDOWN,
                        PLAYING, ROUND_TRANSITION, GAME_OVER, SCORE_SUBMIT)
    effects.py          flying halves, juice splat particles, popups, shake, red flash
    audio.py            pygame.mixer wrapper (silent no-op on any failure)
    renderer.py         camera feed + sprites + HUD + phase overlays + idle menu
  persistence/
    db.py               SQLite connection + schema
    leaderboard.py      insert/top-N repository (write failures never crash the booth)
  tools/
    calibrate.py        HSV/exposure calibration UI (also launchable from Settings)
    generate_sprites.py / generate_sounds.py   deterministic asset generators
    list_cameras.py     find camera indices (informational)
    test_capture.py     live capture smoke test
assets/
  fonts/                Bangers-Regular.ttf (picked up automatically)
  models/               hand_landmarker.task (auto-downloaded on first hand-mode run)
  sprites/              PNG spritesheets
  sounds/               WAV sound effects
tests/                  hardware-independent unit tests (no camera or display required)
```

### Tests

```powershell
.\venv\Scripts\python.exe -m pytest tests/ -v
```

All tests run without a camera or display (synthetic frames, seeded RNGs,
SDL dummy video driver) — safe for CI.

---

### Troubleshooting

| Symptom | Fix |
|---|---|
| "Camera failed to open" | Wrong index (check Settings), busy device (close Teams/Zoom), or Windows camera privacy blocking desktop apps |
| Nothing slices in HSV mode | Run calibration from Settings — the mask must show one clean blob. Check `F1` overlay: "tip lost: True" means no marker found |
| Nothing slices in Hand mode | Ensure good lighting on your hand; keep the background plain; check that MediaPipe model downloaded successfully |
| Slices trigger without moving | Raise `game.slice.min_speed_px_s` in config |
| HSV detection drifts over the day | Exposure/white balance not locked — use Fine-tune Calibration, lock with `e`/`d`, re-save |
| Choppy video | Camera negotiated low fps — confirm `MJPG` accepted in startup logs; try a different USB port |
| "CAMERA DISCONNECTED" banner | USB cable dropped — timer pauses, game auto-reconnects on replug |
| Low fps / stutter | High-performance power plan, plug in AC, close background apps |
| Hand model download hangs | Check internet connection; manually place `hand_landmarker.task` in `assets/models/` |
