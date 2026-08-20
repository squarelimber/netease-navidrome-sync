"""SQLite 状态库：曲目记录、失败重试队列、歌单条目、运行历史。"""

import json
import sqlite3
import time
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS tracks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    key TEXT UNIQUE NOT NULL,          -- 归一化 artist::title
    title TEXT NOT NULL,
    artists TEXT NOT NULL,             -- JSON list
    album TEXT DEFAULT '',
    origin TEXT DEFAULT '',            -- 来源标记，如 netease_daily / playlist:我喜欢的音乐 / listenbrainz / lastfm
    playlist TEXT DEFAULT '',          -- 归属的歌单名（生成 m3u8 用）
    ncm_id INTEGER,
    status TEXT NOT NULL DEFAULT 'pending',  -- pending/downloaded/existed/failed
    fail_reason TEXT DEFAULT '',
    attempts INTEGER DEFAULT 0,
    next_retry_at REAL,
    file_path TEXT DEFAULT '',         -- 相对 music_dir 的路径
    download_source TEXT DEFAULT '',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_tracks_status ON tracks(status);
CREATE INDEX IF NOT EXISTS idx_tracks_retry ON tracks(status, next_retry_at);

CREATE TABLE IF NOT EXISTS playlist_items (
    playlist TEXT NOT NULL,
    track_key TEXT NOT NULL,
    position INTEGER DEFAULT 0,
    added_at REAL NOT NULL,
    PRIMARY KEY (playlist, track_key)
);

CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at REAL NOT NULL,
    finished_at REAL,
    stats TEXT DEFAULT '{}'            -- JSON
);

CREATE TABLE IF NOT EXISTS property (
    key TEXT PRIMARY KEY,
    value TEXT DEFAULT ''
);
"""

SCROBBLE_TS_KEY = "last_scrobble_ts"
SCROBBLE_PENDING_KEY = "scrobble_pending"

# 失败重试退避（天），按 attempts 递增
RETRY_BACKOFF_DAYS = [1, 1, 3, 7, 14, 30, 60]
MAX_ATTEMPTS = len(RETRY_BACKOFF_DAYS) + 1


class DB:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA busy_timeout=5000")
        self.conn.execute("PRAGMA synchronous=NORMAL")
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    # ---------- tracks ----------

    def get_track(self, key: str):
        row = self.conn.execute("SELECT * FROM tracks WHERE key = ?", (key,)).fetchone()
        return dict(row) if row else None

    def upsert_track(self, key, title, artists, album="", origin="", ncm_id=None, playlist=""):
        now = time.time()
        self.conn.execute(
            """INSERT INTO tracks (key, title, artists, album, origin, playlist, ncm_id, status, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,'pending',?,?)
               ON CONFLICT(key) DO UPDATE SET
                 origin = CASE WHEN tracks.origin LIKE '%' || excluded.origin || '%'
                               THEN tracks.origin
                               ELSE tracks.origin || ',' || excluded.origin END,
                 ncm_id = COALESCE(tracks.ncm_id, excluded.ncm_id),
                 album = CASE WHEN tracks.album = '' THEN excluded.album ELSE tracks.album END,
                 playlist = CASE WHEN tracks.playlist = '' THEN excluded.playlist ELSE tracks.playlist END,
                 updated_at = excluded.updated_at""",
            (key, title, json.dumps(artists, ensure_ascii=False), album, origin, playlist, ncm_id, now, now),
        )
        self.conn.commit()

    def mark_downloaded(self, key, file_path, download_source):
        self.conn.execute(
            """UPDATE tracks SET status='downloaded', file_path=?, download_source=?,
               fail_reason='', next_retry_at=NULL, updated_at=? WHERE key=?""",
            (file_path, download_source, time.time(), key),
        )
        self.conn.commit()

    def set_ncm_id(self, key: str, ncm_id: int):
        self.conn.execute(
            "UPDATE tracks SET ncm_id=?, updated_at=? WHERE key=? AND ncm_id IS NULL",
            (ncm_id, time.time(), key),
        )
        self.conn.commit()

    def mark_existed(self, key):
        self.conn.execute(
            "UPDATE tracks SET status='existed', next_retry_at=NULL, updated_at=? WHERE key=?",
            (time.time(), key),
        )
        self.conn.commit()

    def mark_failed(self, key, reason):
        row = self.get_track(key)
        attempts = (row["attempts"] if row else 0) + 1
        days = RETRY_BACKOFF_DAYS[min(attempts - 1, len(RETRY_BACKOFF_DAYS) - 1)]
        next_retry = time.time() + days * 86400 if attempts <= MAX_ATTEMPTS else None
        status = "failed" if next_retry else "dead"
        self.conn.execute(
            """UPDATE tracks SET status=?, fail_reason=?, attempts=?, next_retry_at=?, updated_at=?
               WHERE key=?""",
            (status, reason, attempts, next_retry, time.time(), key),
        )
        self.conn.commit()

    def due_retries(self):
        now = time.time()
        rows = self.conn.execute(
            "SELECT * FROM tracks WHERE status='failed' AND next_retry_at IS NOT NULL AND next_retry_at <= ?",
            (now,),
        ).fetchall()
        return [dict(r) for r in rows]

    def reset_retry(self, track_id: int):
        self.conn.execute(
            "UPDATE tracks SET status='failed', next_retry_at=?, updated_at=? WHERE id=?",
            (time.time(), time.time(), track_id),
        )
        self.conn.commit()

    def list_tracks(self, status=None, limit=200):
        if status:
            rows = self.conn.execute(
                "SELECT * FROM tracks WHERE status=? ORDER BY updated_at DESC LIMIT ?",
                (status, limit),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM tracks ORDER BY updated_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(r) for r in rows]

    def stats(self):
        rows = self.conn.execute(
            "SELECT status, COUNT(*) AS c FROM tracks GROUP BY status"
        ).fetchall()
        return {r["status"]: r["c"] for r in rows}

    # ---------- playlist items ----------

    def playlist_keys(self, playlist: str):
        rows = self.conn.execute(
            "SELECT track_key FROM playlist_items WHERE playlist=? ORDER BY position, added_at",
            (playlist,),
        ).fetchall()
        return [r["track_key"] for r in rows]

    def add_playlist_item(self, playlist: str, key: str, position: int = 0):
        self.conn.execute(
            """INSERT INTO playlist_items (playlist, track_key, position, added_at)
               VALUES (?,?,?,?)
               ON CONFLICT(playlist, track_key) DO UPDATE SET position=excluded.position""",
            (playlist, key, position, time.time()),
        )
        self.conn.commit()

    def tracks_for_playlist(self, playlist: str):
        rows = self.conn.execute(
            """SELECT t.* FROM playlist_items p JOIN tracks t ON t.key = p.track_key
               WHERE p.playlist=? AND t.file_path != '' AND t.status IN ('downloaded','existed')
               ORDER BY p.position, p.added_at""",
            (playlist,),
        ).fetchall()
        return [dict(r) for r in rows]

    def playlist_names(self):
        """返回数据库中所有歌单名称，用于清理过期的自动歌单。"""
        rows = self.conn.execute(
            "SELECT DISTINCT playlist FROM playlist_items WHERE playlist != ''"
        ).fetchall()
        return [r["playlist"] for r in rows]

    def delete_playlist(self, playlist: str):
        """删除歌单关联记录，但保留曲目和实际音频文件。"""
        self.conn.execute("DELETE FROM playlist_items WHERE playlist=?", (playlist,))
        self.conn.commit()

    # ---------- runs ----------

    def run_start(self):
        cur = self.conn.execute("INSERT INTO runs (started_at) VALUES (?)", (time.time(),))
        self.conn.commit()
        return cur.lastrowid

    def run_finish(self, run_id, stats: dict):
        self.conn.execute(
            "UPDATE runs SET finished_at=?, stats=? WHERE id=?",
            (time.time(), json.dumps(stats, ensure_ascii=False), run_id),
        )
        self.conn.commit()

    def list_runs(self, limit=30):
        rows = self.conn.execute(
            "SELECT * FROM runs ORDER BY started_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]

    # ---------- property ----------

    def get_property(self, key: str, default: str = "") -> str:
        row = self.conn.execute("SELECT value FROM property WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else default

    def set_property(self, key: str, value: str):
        self.conn.execute(
            "INSERT OR REPLACE INTO property (key, value) VALUES (?, ?)", (key, value),
        )
        self.conn.commit()

    def close(self):
        self.conn.close()
