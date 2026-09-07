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


def test_delete_playlist_keeps_track(tmp_path):
    db = DB(tmp_path / "test.db")
    db.upsert_track("a::b", "b", ["a"], origin="lastfm",
                    playlist="LastFM-推荐-2026-08-20")
    db.mark_downloaded("a::b", "Discover/a.mp3", "kuwo")
    db.add_playlist_item("LastFM-推荐-2026-08-20", "a::b")
    assert "LastFM-推荐-2026-08-20" in db.playlist_names()
    db.delete_playlist("LastFM-推荐-2026-08-20")
    assert "LastFM-推荐-2026-08-20" not in db.playlist_names()
    assert db.get_track("a::b")["file_path"] == "Discover/a.mp3"
    db.close()


def test_list_tracks_pagination_no_overlap(tmp_path):
    db = DB(tmp_path / "test.db")
    for i in range(25):
        db.upsert_track(f"k{i}::t", f"t{i}", [f"a{i}"])
        db.mark_downloaded(f"k{i}::t", f"Discover/t{i}.mp3", "kuwo")
    total = db.count_tracks("downloaded")
    assert total == 25
    page1 = db.list_tracks("downloaded", limit=10, offset=0)
    page2 = db.list_tracks("downloaded", limit=10, offset=10)
    page3 = db.list_tracks("downloaded", limit=10, offset=20)
    assert len(page1) == 10 and len(page2) == 10 and len(page3) == 5
    keys = [r["key"] for r in page1 + page2 + page3]
    assert len(set(keys)) == 25, "分页之间不应有重叠或遗漏"
    # offset 越界返回空
    assert db.list_tracks("downloaded", limit=10, offset=100) == []
    db.close()


def test_count_tracks_by_status(tmp_path):
    db = DB(tmp_path / "test.db")
    db.upsert_track("k1::t", "t1", ["a1"])
    db.mark_downloaded("k1::t", "Discover/t1.mp3", "kuwo")
    db.upsert_track("k2::t", "t2", ["a2"])  # 仍 pending
    assert db.count_tracks() == 2
    assert db.count_tracks("downloaded") == 1
    assert db.count_tracks("pending") == 1
    db.close()
