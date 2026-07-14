"""SQLite connection ownership + schema. The only module that creates
connections; leaderboard.py (Repository pattern) issues queries through it.
"""
from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    player_name      TEXT NOT NULL DEFAULT 'Player',
    final_score      INTEGER NOT NULL,
    rounds_reached   INTEGER NOT NULL,
    hearts_remaining INTEGER NOT NULL,
    max_combo        INTEGER NOT NULL DEFAULT 0,
    played_at        TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_sessions_score ON sessions (final_score DESC);
"""


@dataclass
class SessionRecord:
    player_name: str
    final_score: int
    rounds_reached: int
    hearts_remaining: int
    max_combo: int


def connect(db_path: str) -> sqlite3.Connection:
    """Create the data dir if needed, open the connection, run the
    idempotent schema DDL."""
    directory = os.path.dirname(db_path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.executescript(_SCHEMA)
    conn.commit()
    return conn
