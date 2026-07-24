"""Leaderboard repository — the only module that constructs SQL for game
logic. A failed write must never crash the booth (retry once, then drop).
"""
from __future__ import annotations

import logging
import sqlite3
import time
from typing import List

from src.persistence import db
from src.persistence.db import SessionRecord

log = logging.getLogger(__name__)


class Leaderboard:
    def __init__(self, db_path: str):
        self._conn = db.connect(db_path)

    def insert_session(self, record: SessionRecord) -> None:
        sql = (
            "INSERT INTO sessions (player_name, final_score, rounds_reached, "
            "hearts_remaining, max_combo) VALUES (?, ?, ?, ?, ?)"
        )
        params = (
            record.player_name,
            record.final_score,
            record.rounds_reached,
            record.hearts_remaining,
            record.max_combo,
        )
        try:
            self._conn.execute(sql, params)
            self._conn.commit()
        except sqlite3.OperationalError as exc:
            log.warning("leaderboard write failed (%s) — retrying once", exc)
            time.sleep(0.2)
            try:
                self._conn.execute(sql, params)
                self._conn.commit()
            except sqlite3.OperationalError as exc2:
                log.error("leaderboard write failed twice, dropping session: %s", exc2)

    def get_top(self, n: int) -> List[SessionRecord]:
        rows = self._conn.execute(
            "SELECT player_name, final_score, rounds_reached, hearts_remaining, max_combo "
            "FROM sessions ORDER BY final_score DESC, played_at ASC LIMIT ?",
            (n,),
        ).fetchall()
        return [SessionRecord(*row) for row in rows]

    def get_history(self, limit: int = 200) -> List[tuple]:
        """Recent sessions newest-first with timestamps, for the history view.
        Returns raw tuples (name, score, rounds, max_combo, played_at) since the
        display needs played_at, which SessionRecord does not carry."""
        return self._conn.execute(
            "SELECT player_name, final_score, rounds_reached, max_combo, played_at "
            "FROM sessions ORDER BY played_at DESC, id DESC LIMIT ?",
            (limit,),
        ).fetchall()

    def clear(self) -> None:
        """Wipe all saved sessions (leaderboard + history). Booth-safe: a
        failed reset is logged, never raised."""
        try:
            self._conn.execute("DELETE FROM sessions")
            self._conn.commit()
        except sqlite3.OperationalError as exc:
            log.error("leaderboard reset failed: %s", exc)

    def close(self) -> None:
        self._conn.close()
