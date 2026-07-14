import os
import wave

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import numpy as np
import pygame
import pytest

from src.tools import generate_sounds, generate_sprites


@pytest.fixture(scope="module")
def sprite_dir(tmp_path_factory):
    out = tmp_path_factory.mktemp("sprites")
    generate_sprites.generate(str(out))
    return out


@pytest.fixture(scope="module")
def sound_dir(tmp_path_factory):
    out = tmp_path_factory.mktemp("sounds")
    generate_sounds.generate(str(out))
    return out


def test_all_manifest_sprites_exist(sprite_dir):
    for name in generate_sprites.expected_files():
        assert (sprite_dir / name).is_file(), f"missing {name}"


def test_sprites_are_256_rgba_with_content(sprite_dir):
    pygame.init()
    for name in generate_sprites.expected_files():
        surf = pygame.image.load(str(sprite_dir / name))
        assert surf.get_size() == (256, 256), name
        alpha = pygame.surfarray.array_alpha(surf)
        visible_frac = (alpha > 30).mean()
        assert visible_frac > 0.05, f"{name} is nearly empty ({visible_frac:.3f})"


def test_halves_differ_from_each_other(sprite_dir):
    pygame.init()
    for fruit in generate_sprites.FRUITS:
        a1 = pygame.surfarray.array_alpha(pygame.image.load(str(sprite_dir / f"{fruit}_half_1.png")))
        a2 = pygame.surfarray.array_alpha(pygame.image.load(str(sprite_dir / f"{fruit}_half_2.png")))
        assert not np.array_equal(a1, a2), fruit


def test_sounds_valid_wavs(sound_dir):
    names = ["slice_1", "slice_2", "slice_3", "bomb", "beep", "go", "round_clear", "game_over"]
    for name in names:
        path = sound_dir / f"{name}.wav"
        assert path.is_file()
        with wave.open(str(path), "rb") as wf:
            assert wf.getframerate() == 44100
            assert wf.getsampwidth() == 2
            assert wf.getnchannels() == 1
            assert wf.getnframes() > 0


def test_generation_is_deterministic(tmp_path):
    a = tmp_path / "a"
    b = tmp_path / "b"
    generate_sounds.generate(str(a))
    generate_sounds.generate(str(b))
    for name in os.listdir(a):
        assert (a / name).read_bytes() == (b / name).read_bytes(), name
