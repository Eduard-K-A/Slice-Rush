"""Fire-and-forget sound effects. The booth must run silently rather than
crash over an audio device: any mixer failure makes this a permanent no-op.
"""
from __future__ import annotations

import itertools
import logging
import os

import pygame

from src.config_loader import AudioConfig

log = logging.getLogger(__name__)

MANIFEST = [
    "slice_1", "slice_2", "slice_3",
    "bomb", "beep", "go", "round_clear", "game_over",
]


class AudioPlayer:
    def __init__(self, config: AudioConfig, sounds_dir: str):
        self._sounds: dict[str, pygame.mixer.Sound] = {}
        self._enabled = False
        self._slice_cycle = itertools.cycle(["slice_1", "slice_2", "slice_3"])
        if not config.enabled:
            log.info("audio disabled by config")
            return
        try:
            pygame.mixer.init()
        except Exception as exc:  # pragma: no cover - device dependent
            log.warning("pygame.mixer failed to init (%s) — running silent", exc)
            return
        for name in MANIFEST:
            path = os.path.join(sounds_dir, f"{name}.wav")
            if not os.path.isfile(path):
                log.info("sound file missing, skipping: %s", path)
                continue
            try:
                sound = pygame.mixer.Sound(path)
                sound.set_volume(config.volume)
                self._sounds[name] = sound
            except pygame.error as exc:
                log.warning("failed to load sound %s: %s", path, exc)
        self._enabled = bool(self._sounds)

    def play(self, name: str) -> None:
        if not self._enabled:
            return
        if name == "slice":
            name = next(self._slice_cycle)
        sound = self._sounds.get(name)
        if sound is not None:
            sound.play()
