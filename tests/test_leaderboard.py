from src.persistence.db import SessionRecord
from src.persistence.leaderboard import Leaderboard


def make_record(name, score):
    return SessionRecord(
        player_name=name, final_score=score, rounds_reached=2, hearts_remaining=1, max_combo=4
    )


def test_insert_and_top_n(tmp_path):
    lb = Leaderboard(str(tmp_path / "test.db"))
    lb.insert_session(make_record("Alice", 120))
    lb.insert_session(make_record("Bob", 300))
    lb.insert_session(make_record("Cara", 80))
    top2 = lb.get_top(2)
    assert [(r.player_name, r.final_score) for r in top2] == [("Bob", 300), ("Alice", 120)]
    lb.close()


def test_schema_idempotent_reopen(tmp_path):
    path = str(tmp_path / "test.db")
    lb1 = Leaderboard(path)
    lb1.insert_session(make_record("Alice", 10))
    lb1.close()
    lb2 = Leaderboard(path)  # re-running DDL must not fail or wipe data
    assert len(lb2.get_top(10)) == 1
    lb2.close()


def test_record_roundtrip_fields(tmp_path):
    lb = Leaderboard(str(tmp_path / "test.db"))
    lb.insert_session(make_record("Zed", 55))
    row = lb.get_top(1)[0]
    assert row == make_record("Zed", 55)
    lb.close()
