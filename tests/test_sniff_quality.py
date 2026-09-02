"""sniff_quality 音质读取 + tracks.quality 列测试。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.downloader import sniff_quality
from app.db import DB


def test_sniff_quality_fallback_non_audio(tmp_path):
    """非音频文件 → 返回扩展名大写。"""
    p = tmp_path / "notes.txt"
    p.write_text("hello")
    assert sniff_quality(p) == "TXT"


def test_sniff_quality_fallback_missing(tmp_path):
    """不存在的文件 → 返回扩展名大写（异常被吞）。"""
    p = tmp_path / "ghost.mp3"
    assert sniff_quality(p) == "MP3"


def test_sniff_quality_fallback_no_ext(tmp_path):
    """无扩展名 → 返回 AUDIO。"""
    p = tmp_path / "noext"
    p.write_text("x")
    assert sniff_quality(p) == "AUDIO"


def test_db_quality_column(tmp_path):
    """tracks 表有 quality 列，mark_downloaded 可写入并读回。"""
    db = DB(tmp_path / "t.db")
    db.upsert_track("a::b", "B", ["A"])
    db.mark_downloaded("a::b", "x/y.mp3", "netease", "MP3 320k")
    row = db.get_track("a::b")
    assert row["quality"] == "MP3 320k"
    assert row["status"] == "downloaded"
    db.close()


def test_db_quality_default_empty(tmp_path):
    """旧调用（不传 quality）→ 默认空串，不报错。"""
    db = DB(tmp_path / "t.db")
    db.upsert_track("a::b", "B", ["A"])
    db.mark_downloaded("a::b", "x/y.mp3", "kuwo")
    row = db.get_track("a::b")
    assert row["quality"] == ""
    db.close()


def test_db_migration_adds_quality(tmp_path):
    """旧库（无 quality 列）→ 打开后自动补列。"""
    import sqlite3
    conn = sqlite3.connect(str(tmp_path / "old.db"))
    conn.execute("""CREATE TABLE tracks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        key TEXT UNIQUE NOT NULL, title TEXT NOT NULL, artists TEXT NOT NULL,
        album TEXT DEFAULT '', origin TEXT DEFAULT '', playlist TEXT DEFAULT '',
        ncm_id INTEGER, status TEXT NOT NULL DEFAULT 'pending',
        fail_reason TEXT DEFAULT '', attempts INTEGER DEFAULT 0,
        next_retry_at REAL, file_path TEXT DEFAULT '', download_source TEXT DEFAULT '',
        created_at REAL NOT NULL, updated_at REAL NOT NULL)""")
    conn.commit()
    conn.close()
    # 打开旧库，应自动补 quality 列
    db = DB(tmp_path / "old.db")
    row = db.conn.execute("PRAGMA table_info(tracks)").fetchall()
    cols = {r[1] for r in row}
    assert "quality" in cols
    db.close()
