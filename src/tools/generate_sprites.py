"""Deterministic fruit/object sprite generator.

Renders every sprite in the manifest as a 256x256 RGBA PNG: recognizable
cartoon fruit (whole + two sliced halves each), bomb and rock. Drawn at
512x512 and smoothscaled to 256x256 for anti-aliasing. Seeded RNG so
regeneration is byte-reproducible (tested by tests/test_assets.py).

Run: python -m src.tools.generate_sprites [output_dir]
"""
from __future__ import annotations

import os
import random
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import numpy as np
import pygame

S = 512          # draw resolution
OUT = 256        # output resolution
OUTLINE = (45, 32, 32)
OUTLINE_W = 12   # ~6 px at output size

FRUITS = ["apple", "banana", "strawberry", "pineapple", "watermelon"]
BAD = ["bomb", "rock"]

CUT_FACE = {
    "apple": (255, 240, 205),
    "banana": (250, 240, 190),
    "strawberry": (250, 120, 140),
    "pineapple": (250, 225, 110),
    "watermelon": (235, 70, 90),
}


def _surface() -> pygame.Surface:
    return pygame.Surface((S, S), pygame.SRCALPHA)


def _mask_outside_circle(surf: pygame.Surface, center, radius) -> None:
    alpha = pygame.surfarray.pixels_alpha(surf)
    xs, ys = np.meshgrid(np.arange(S), np.arange(S), indexing="ij")
    outside = (xs - center[0]) ** 2 + (ys - center[1]) ** 2 > radius**2
    alpha[outside] = 0
    del alpha


def _mask_outside_ellipse(surf: pygame.Surface, center, rx, ry) -> None:
    alpha = pygame.surfarray.pixels_alpha(surf)
    xs, ys = np.meshgrid(np.arange(S), np.arange(S), indexing="ij")
    outside = ((xs - center[0]) / rx) ** 2 + ((ys - center[1]) / ry) ** 2 > 1.0
    alpha[outside] = 0
    del alpha


# --------------------------------------------------------------------------- fruit recipes


def draw_apple() -> pygame.Surface:
    surf = _surface()
    center, r = (256, 280), 150
    pygame.draw.circle(surf, (210, 40, 45), center, r)
    pygame.draw.circle(surf, OUTLINE, center, r, OUTLINE_W)
    pygame.draw.ellipse(surf, (245, 120, 120), pygame.Rect(180, 190, 90, 64))
    pygame.draw.rect(surf, (100, 60, 30), pygame.Rect(246, 90, 20, 60), border_radius=8)
    pygame.draw.ellipse(surf, (70, 160, 60), pygame.Rect(270, 100, 95, 48))
    return surf


def draw_banana() -> pygame.Surface:
    body = _surface()
    pygame.draw.circle(body, (250, 210, 60), (256, 300), 190)
    eraser = _surface()
    pygame.draw.circle(eraser, (0, 0, 0, 255), (256, 150), 190)
    body.blit(eraser, (0, 0), special_flags=pygame.BLEND_RGBA_SUB)
    # brown tips at the crescent ends
    pygame.draw.circle(body, (120, 80, 40), (92, 350), 20)
    pygame.draw.circle(body, (120, 80, 40), (420, 350), 20)
    return body


def draw_strawberry() -> pygame.Surface:
    surf = _surface()
    body = [(150, 190), (362, 190), (268, 420), (244, 420)]
    pygame.draw.polygon(surf, (220, 30, 60), body)
    pygame.draw.circle(surf, (220, 30, 60), (190, 205), 62)
    pygame.draw.circle(surf, (220, 30, 60), (322, 205), 62)
    pygame.draw.circle(surf, (220, 30, 60), (256, 390), 34)
    # seeds — staggered grid
    for row in range(5):
        for col in range(4):
            x = 180 + col * 44 + (22 if row % 2 else 0)
            y = 210 + row * 40
            if 150 < x < 362 and y < 400 - row * 8:
                pygame.draw.ellipse(surf, (250, 235, 160), pygame.Rect(x, y, 12, 18))
    # calyx — three green leaves on top
    for pts in (
        [(200, 180), (256, 120), (250, 185)],
        [(230, 180), (256, 105), (282, 180)],
        [(262, 185), (312, 120), (312, 180)],
    ):
        pygame.draw.polygon(surf, (70, 165, 65), pts)
    return surf


def draw_pineapple() -> pygame.Surface:
    body = _surface()
    cx, cy, rx, ry = 256, 300, 105, 150
    pygame.draw.ellipse(body, (225, 170, 60), pygame.Rect(cx - rx, cy - ry, rx * 2, ry * 2))
    for offset in range(-260, 300, 52):
        pygame.draw.line(body, (170, 120, 40), (cx - rx + offset, cy - ry), (cx - rx + offset + 210, cy + ry), 8)
        pygame.draw.line(body, (170, 120, 40), (cx + rx - offset, cy - ry), (cx + rx - offset - 210, cy + ry), 8)
    _mask_outside_ellipse(body, (cx, cy), rx, ry)
    # spiky green crown, drawn after masking so it extends past the ellipse
    for i in range(6):
        x = 190 + i * 26
        tip = (x + 13 + (i - 3) * 10, 60 + abs(i - 3) * 14)
        pygame.draw.polygon(body, (60, 150, 60), [(x, 170), (x + 30, 170), tip])
    return body


def draw_watermelon() -> pygame.Surface:
    body = _surface()
    center, r = (256, 266), 170
    pygame.draw.circle(body, (35, 120, 50), center, r)
    for i in range(5):
        x = 130 + i * 62
        pygame.draw.line(body, (90, 175, 90), (x - 20, 96), (x + 20, 436), 26)
    _mask_outside_circle(body, center, r)
    pygame.draw.circle(body, (25, 90, 40), center, r, OUTLINE_W)
    return body


def draw_bomb() -> pygame.Surface:
    surf = _surface()
    center, r = (256, 290), 160
    pygame.draw.circle(surf, (38, 38, 44), center, r)
    pygame.draw.ellipse(surf, (110, 110, 122), pygame.Rect(175, 200, 84, 58))
    pygame.draw.rect(surf, (60, 60, 68), pygame.Rect(226, 110, 60, 40), border_radius=10)
    pygame.draw.line(surf, (130, 90, 50), (256, 112), (300, 66), 14)
    pygame.draw.line(surf, (130, 90, 50), (300, 66), (330, 62), 14)
    # 4-point spark star at the fuse end
    star_center = (344, 56)
    for dx, dy in ((26, 0), (-26, 0), (0, 26), (0, -26)):
        pygame.draw.polygon(
            surf,
            (255, 210, 70),
            [
                (star_center[0] + dx, star_center[1] + dy),
                (star_center[0] + dy // 3, star_center[1] + dx // 3),
                (star_center[0] - dy // 3, star_center[1] - dx // 3),
            ],
        )
    pygame.draw.circle(surf, (255, 150, 40), star_center, 12)
    return surf


def draw_rock(rng: random.Random) -> pygame.Surface:
    surf = _surface()
    cx, cy = 256, 276
    points = []
    n = 8
    for i in range(n):
        angle = 2 * np.pi * i / n
        radius = 150 + rng.uniform(-30, 30)
        points.append((cx + radius * np.cos(angle), cy + radius * np.sin(angle)))
    pygame.draw.polygon(surf, (120, 120, 126), points)
    # lighter top facet + darker facet lines
    top = [points[5], points[6], points[7], (cx, cy)]
    pygame.draw.polygon(surf, (150, 150, 156), top)
    pygame.draw.line(surf, (90, 90, 96), points[1], (cx, cy), 8)
    pygame.draw.line(surf, (90, 90, 96), points[3], (cx, cy), 8)
    return surf


# --------------------------------------------------------------------------- halves

FACE_HALF_WIDTH = 44  # cut-face strip width at 512 res (~22px at output)


def make_halves(whole: pygame.Surface, subtype: str) -> tuple[pygame.Surface, pygame.Surface]:
    alpha = pygame.surfarray.array_alpha(whole)  # indexed [x][y]
    near_cut = alpha[246:266, :].max(axis=0)
    ys = np.nonzero(near_cut > 100)[0]
    y_min, y_max = (int(ys.min()), int(ys.max())) if len(ys) else (120, 400)

    halves = []
    for side in (0, 1):
        half = _surface()
        src = pygame.Rect(0, 0, 256, S) if side == 0 else pygame.Rect(256, 0, 256, S)
        half.blit(whole, src.topleft, src)

        face = _surface()
        face_rect = pygame.Rect(256 - FACE_HALF_WIDTH, y_min, FACE_HALF_WIDTH * 2, max(2, y_max - y_min))
        pygame.draw.ellipse(face, CUT_FACE[subtype], face_rect)
        if subtype == "watermelon":  # seeds on the red flesh
            for i in range(3):
                pygame.draw.ellipse(
                    face, (25, 25, 25), pygame.Rect(250, y_min + 40 + i * (y_max - y_min - 80) // 2, 12, 20)
                )
        # confine the face to the fruit silhouette and the kept side
        face_alpha = pygame.surfarray.pixels_alpha(face)
        face_alpha[alpha < 100] = 0
        if side == 0:
            face_alpha[258:, :] = 0
        else:
            face_alpha[:254, :] = 0
        del face_alpha
        half.blit(face, (0, 0))
        halves.append(half)
    return halves[0], halves[1]


# --------------------------------------------------------------------------- main


def generate(out_dir: str) -> list[str]:
    pygame.init()
    rng = random.Random(7)
    os.makedirs(out_dir, exist_ok=True)
    drawers = {
        "apple": draw_apple,
        "banana": draw_banana,
        "strawberry": draw_strawberry,
        "pineapple": draw_pineapple,
        "watermelon": draw_watermelon,
        "bomb": draw_bomb,
        "rock": lambda: draw_rock(rng),
    }
    written = []
    for name, drawer in drawers.items():
        whole = drawer()
        surfaces = {name: whole}
        if name in FRUITS:
            h1, h2 = make_halves(whole, name)
            surfaces[f"{name}_half_1"] = h1
            surfaces[f"{name}_half_2"] = h2
        for key, surf in surfaces.items():
            out = pygame.transform.smoothscale(surf, (OUT, OUT))
            path = os.path.join(out_dir, f"{key}.png")
            pygame.image.save(out, path)
            written.append(path)
    return written


def expected_files() -> list[str]:
    files = []
    for f in FRUITS:
        files += [f"{f}.png", f"{f}_half_1.png", f"{f}_half_2.png"]
    files += [f"{b}.png" for b in BAD]
    return files


def main() -> int:
    out_dir = sys.argv[1] if len(sys.argv) > 1 else "assets/sprites"
    written = generate(out_dir)
    expected = set(expected_files())
    produced = {os.path.basename(p) for p in written}
    missing = expected - produced
    for p in sorted(written):
        print("wrote", p)
    if missing:
        print("ERROR: missing sprites:", sorted(missing))
        return 1
    print(f"OK — {len(written)} sprites in {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
