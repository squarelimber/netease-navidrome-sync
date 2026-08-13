"""DB 初始化（WAL 模式）测试。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db import DB


def test_db_uses_wal(tmp_path):
    db = DB(tmp_path / "test.db")
    mode = db.conn.execute("PRAGMA journal_mode").fetchone()[0]
    assert str(mode).lower() == "wal"
    db.close()


def test_db_basic_ops(tmp_path):
    db = DB(tmp_path / "test.db")
    db.upsert_track("a::b", "b", ["a"], origin="test")
    row = db.get_track("a::b")
    assert row["status"] == "pending"
    db.mark_downloaded("a::b", "x/y.mp3", "netease")
    assert db.get_track("a::b")["status"] == "downloaded"
    db.close()
