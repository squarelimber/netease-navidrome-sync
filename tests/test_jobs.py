"""歌词合并与聚合逻辑测试。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import datetime
import types

from app.jobs import Jobs, _merge_lrc
from app.sources.base import Track
from app.util import track_key

OLRC = """[00:01.00]第一句
[00:05.00]第二句
[00:10.00]第三句"""

TLRC = """[00:01.00]First line
[00:05.00]Second line"""


def test_merge_lrc_with_translation():
    merged = _merge_lrc(OLRC, TLRC)
    lines = merged.splitlines()
    assert "[00:01.00]第一句" in lines
    assert "[00:01.00]First line" in lines
    # 翻译紧跟原文
    i = lines.index("[00:01.00]第一句")
    assert lines[i + 1] == "[00:01.00]First line"
    # 无翻译的行不变
    assert "[00:10.00]第三句" in lines
    assert lines[-1] == "[00:10.00]第三句"


def test_merge_lrc_no_translation():
    assert _merge_lrc(OLRC, None) == OLRC


def test_merge_lrc_no_original():
    assert _merge_lrc(None, TLRC) is None


class _TrackDB:
    """按 key 提供 tracks 表状态，供聚合测试使用。"""

    def __init__(self, statuses: dict[str, str]):
        self._statuses = statuses

    def get_track(self, key):
        if key in self._statuses:
            return {"key": key, "status": self._statuses[key]}
        return None


def _agg_jobs(limit, statuses):
    import types
    jobs = types.SimpleNamespace()
    jobs.cfg = types.SimpleNamespace(daily_discover_limit=limit)
    jobs.db = _TrackDB(statuses)
    return jobs


def test_aggregate_daily_unlimited_and_merging():
    today = datetime.date.today().isoformat()
    tracks = [
        Track(title="日推A", artists=["X"], origin="netease_daily", score=0.9),
        Track(title="日推B", artists=["Y"], origin="netease_daily", score=0.89),
        Track(title="歌A", artists=["Z"], origin="listenbrainz", score=0.9),
        Track(title="歌A", artists=["Z"], origin="lastfm", score=0.8),   # 多源重复
        Track(title="歌B", artists=["W"], origin="lastfm", score=0.7),
        Track(title="歌C", artists=["V"], origin="listenbrainz", score=0.5),
    ]
    out = Jobs._aggregate_discover(_agg_jobs(10, {}), tracks)

    # 日推 2 首原样保留（不限额），其余合并为 每日发现
    daily = [t for t in out if t.origin.startswith("netease_daily")]
    found = [t for t in out if not t.origin.startswith("netease_daily")]
    assert len(daily) == 2
    assert {t.title for t in daily} == {"日推A", "日推B"}
    # 多源重复的歌A 只出现一次，来源合并
    song_a = next(t for t in found if t.title == "歌A")
    assert "listenbrainz" in song_a.origin and "lastfm" in song_a.origin
    assert song_a.playlist == f"每日发现-{today}"
    assert len(found) == 3


def test_aggregate_caps_at_limit_by_score():
    tracks = [
        Track(title=f"歌{i}", artists=["A"], origin="lastfm", score=0.5 + i * 0.01)
        for i in range(15)
    ]
    out = Jobs._aggregate_discover(_agg_jobs(10, {}), tracks)
    assert len(out) == 10
    scores = [t.score for t in out]
    assert scores == sorted(scores, reverse=True)
    # 分数最高的入选
    assert out[0].title == "歌14"


def test_aggregate_excludes_known_tracks():
    known_key = track_key(["Z"], "已下过的歌")
    tracks = [
        Track(title="已下过的歌", artists=["Z"], origin="listenbrainz", score=0.99),
        Track(title="新歌A", artists=["A"], origin="lastfm", score=0.5),
        Track(title="新歌B", artists=["B"], origin="lastfm", score=0.4),
    ]
    db_status = {known_key: "downloaded"}
    out = Jobs._aggregate_discover(_agg_jobs(10, db_status), tracks)
    assert {t.title for t in out} == {"新歌A", "新歌B"}
    # 已收过的歌不占名额：限额为 2 时两首新歌都能进
    out2 = Jobs._aggregate_discover(_agg_jobs(2, db_status), tracks)
    assert {t.title for t in out2} == {"新歌A", "新歌B"}


def test_aggregate_failed_tracks_can_retry():
    """失败过的歌允许再次入选（走重试队列）。"""
    failed_key = track_key(["Z"], "失败的歌")
    tracks = [
        Track(title="失败的歌", artists=["Z"], origin="listenbrainz", score=0.9),
    ]
    out = Jobs._aggregate_discover(_agg_jobs(10, {failed_key: "failed"}), tracks)
    assert len(out) == 1


class _FakeSubsonic:
    def __init__(self, playlists, deleted_ok=True):
        self._playlists = playlists
        self.deleted = []
        self._ok = deleted_ok

    def list_playlists(self):
        self.listed = True
        return self._playlists

    def delete_playlist(self, pid):
        if self._ok:
            self.deleted.append(pid)
            return True
        return False


class _FakeDB:
    def __init__(self, names):
        self._names = names
        self.deleted = []

    def playlist_names(self):
        return list(self._names)

    def delete_playlist(self, name):
        self.deleted.append(name)


def _cleanup_fn(music_dir, db, subsonic):
    jobs = types.SimpleNamespace()
    jobs.cfg = types.SimpleNamespace(music_dir=music_dir, playlist_retention_days=3)
    jobs.db = db
    jobs.subsonic = subsonic
    return lambda: Jobs._cleanup_old_playlists(jobs)


def test_cleanup_deletes_navidrome_playlist(tmp_path):
    old = (datetime.date.today() - datetime.timedelta(days=3)).isoformat()
    stale = f"网易云日推-{old}"
    new = f"网易云日推-{datetime.date.today().isoformat()}"
    discover = tmp_path / "Discover"
    discover.mkdir()
    (discover / f"{stale}.m3u8").write_text("#EXTM3U", encoding="utf-8")
    (discover / f"{new}.m3u8").write_text("#EXTM3U", encoding="utf-8")

    navi_pls = [
        {"id": "1", "name": f"{stale}.m3u8"},  # Navidrome 导入时带扩展名
        {"id": "2", "name": new},
        {"id": "3", "name": "Weekly Jams"},
    ]
    sub = _FakeSubsonic(navi_pls)
    db = _FakeDB({stale, new})
    fn = _cleanup_fn(tmp_path, db, sub)()

    assert sub.deleted == ["1"]           # 只删过期的，且按归一化名匹配
    assert db.deleted == [stale]
    assert not (discover / f"{stale}.m3u8").exists()
    assert (discover / f"{new}.m3u8").exists()


def test_cleanup_navidrome_failure_not_fatal(tmp_path):
    old = (datetime.date.today() - datetime.timedelta(days=3)).isoformat()
    stale = f"ListenBrainz-CF-{old}"
    discover = tmp_path / "Discover"
    discover.mkdir()
    sub = _FakeSubsonic([{"id": "9", "name": stale}], deleted_ok=False)
    db = _FakeDB({stale})
    fn = _cleanup_fn(tmp_path, db, sub)()

    assert sub.deleted == []              # API 失败不阻断
    assert db.deleted == [stale]          # 本地清理照常


def test_cleanup_without_subsonic(tmp_path):
    old = (datetime.date.today() - datetime.timedelta(days=3)).isoformat()
    stale = f"LastFM-推荐-{old}"
    db = _FakeDB({stale})
    fn = _cleanup_fn(tmp_path, db, None)()

    assert db.deleted == [stale]


def test_cleanup_no_local_candidates_still_scans_navidrome(tmp_path):
    """无本地过期记录时仍扫描 Navidrome（为清理孤儿歌单）；无孤儿则不删任何东西。"""
    sub = _FakeSubsonic([{"id": "1", "name": "whatever"}])
    db = _FakeDB(set())
    fn = _cleanup_fn(tmp_path, db, sub)()

    assert getattr(sub, "listed", False) is True   # 仍会扫描 Navidrome
    assert sub.deleted == []
    assert db.deleted == []


def test_cleanup_removes_orphaned_navidrome_playlist(tmp_path):
    """本地记录已清、Navidrome 残留的孤儿歌单：下次运行仍能删掉。"""
    old = (datetime.date.today() - datetime.timedelta(days=3)).isoformat()
    orphan = f"网易云日推-{old}"
    sub = _FakeSubsonic([{"id": "7", "name": orphan}])
    db = _FakeDB(set())   # 本地无任何记录（文件与数据库均已清理）
    fn = _cleanup_fn(tmp_path, db, sub)()

    assert sub.deleted == ["7"]
    assert db.deleted == []


def test_cleanup_orphan_name_with_extension(tmp_path):
    """孤儿歌单名带 .m3u8 扩展名（Navidrome 导入时保留）也能识别删除。"""
    old = (datetime.date.today() - datetime.timedelta(days=5)).isoformat()
    orphan = f"每日发现-{old}"
    sub = _FakeSubsonic([{"id": "8", "name": f"{orphan}.m3u8"}])
    db = _FakeDB(set())
    fn = _cleanup_fn(tmp_path, db, sub)()

    assert sub.deleted == ["8"]


def test_cleanup_keeps_current_and_user_playlists(tmp_path):
    """未过期的自动歌单与用户自建歌单一律不动。"""
    today = datetime.date.today().isoformat()
    yesterday = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()
    sub = _FakeSubsonic([
        {"id": "1", "name": f"每日发现-{today}"},      # 今天，保留
        {"id": "2", "name": f"网易云日推-{yesterday}"},  # 保留期（3天）内，保留
        {"id": "3", "name": "我喜欢的音乐"},
        {"id": "4", "name": "Weekly Jams"},
    ])
    db = _FakeDB(set())
    fn = _cleanup_fn(tmp_path, db, sub)()

    assert sub.deleted == []
    assert db.deleted == []


def test_cleanup_returns_stats_for_web_button(tmp_path):
    """手动清理按钮依赖的返回值：候选数 / Navidrome 删除数 / 文件删除数。"""
    old = (datetime.date.today() - datetime.timedelta(days=3)).isoformat()
    stale = f"网易云日推-{old}"
    discover = tmp_path / "Discover"
    discover.mkdir()
    (discover / f"{stale}.m3u8").write_text("#EXTM3U", encoding="utf-8")
    sub = _FakeSubsonic([{"id": "1", "name": stale}])
    db = _FakeDB({stale})
    stats = _cleanup_fn(tmp_path, db, sub)()

    assert stats == {"candidates": 1, "navi_deleted": 1, "files_deleted": 1}


# ---- 打卡（scrobble）复用库内 ncm_id ----

def _scrobble_jobs(lib_rows, listens, ncm):
    """搭最小 Jobs 对象跑 _scrobble_recent。lib_rows: list_tracks 返回；listens: LB 播放。"""
    import types

    class _DB:
        def __init__(self, rows):
            self._rows = rows
            self._props = {}
        def get_property(self, key, default=""):
            return self._props.get(key, default)
        def set_property(self, key, value):
            self._props[key] = value
        def list_tracks(self, status=None, limit=200):
            return self._rows

    jobs = types.SimpleNamespace()
    jobs.cfg = types.SimpleNamespace(
        sources={"listenbrainz": types.SimpleNamespace(
            enabled=True, extra={"username": "chococake"})},
        title_threshold=85, max_duration_diff=12,
    )
    jobs.last_cookie_ok = True
    jobs.db = _DB(lib_rows)
    jobs.ncm = ncm
    jobs.scrobble_limiter = types.SimpleNamespace(wait=lambda: None)
    return jobs


class _RecNCM:
    def __init__(self, search_results=None):
        self.search_calls = []
        self.scrobble_calls = []
        self._search_results = search_results or []
    def search(self, keyword, limit=5):
        self.search_calls.append(keyword)
        return self._search_results
    def scrobble(self, ncm_id, time_ms):
        self.scrobble_calls.append((ncm_id, time_ms))
        return True


def test_scrobble_uses_library_ncm_id(monkeypatch):
    """库内已下载（有 ncm_id）的歌：打卡直接复用，不搜索网易云。"""
    from app import jobs as jobs_mod
    lib_artist, lib_title, lib_ncm_id = "周杰伦", "东风破", 99999
    lib_key = track_key([lib_artist], lib_title)
    lib_rows = [{"key": lib_key, "title": lib_title, "ncm_id": lib_ncm_id,
                 "status": "downloaded"}]
    listens = [{"listened_at": 1000, "artist": lib_artist, "title": lib_title,
                "duration_ms": 260000}]
    monkeypatch.setattr(jobs_mod, "get_recent_listens",
                        lambda username, min_ts=0: listens)
    ncm = _RecNCM()
    jobs = _scrobble_jobs(lib_rows, listens, ncm)
    result = Jobs._scrobble_recent(jobs)
    assert ncm.search_calls == [], "库内命中不应再搜索网易云"
    assert ncm.scrobble_calls == [(lib_ncm_id, 260000)]
    assert result["ok"] is True and result["count"] == 1 and result["fail"] == 0


def test_scrobble_title_fallback_when_artist_differs(monkeypatch):
    """artist 完全对不上（key 拆不出库内首艺术家）但标题库内唯一 → 标题兜底命中。"""
    from app import jobs as jobs_mod
    lib_title, lib_ncm_id = "东风破", 88888
    # 库里 artist 是"周杰伦"，LB 播放 artist 是英文名"Jay Chou"（key 怎么拆都对不上）
    lib_rows = [{"key": track_key(["周杰伦"], lib_title), "title": lib_title,
                 "ncm_id": lib_ncm_id, "status": "downloaded"}]
    listens = [{"listened_at": 1000, "artist": "Jay Chou", "title": lib_title,
                "duration_ms": 260000}]
    monkeypatch.setattr(jobs_mod, "get_recent_listens",
                        lambda username, min_ts=0: listens)
    ncm = _RecNCM()
    jobs = _scrobble_jobs(lib_rows, listens, ncm)
    result = Jobs._scrobble_recent(jobs)
    assert ncm.search_calls == [], "标题唯一兜底命中不应再搜索"
    assert ncm.scrobble_calls == [(lib_ncm_id, 260000)]
    assert result["ok"] is True and result["count"] == 1


def test_scrobble_falls_back_to_search_when_not_in_library(monkeypatch):
    """库内没有的歌 → 仍走网易云搜索。"""
    from app import jobs as jobs_mod
    listens = [{"listened_at": 1000, "artist": "某新人", "title": "未知之歌",
                "duration_ms": 200000}]
    monkeypatch.setattr(jobs_mod, "get_recent_listens",
                        lambda username, min_ts=0: listens)
    ncm = _RecNCM(search_results=[{"id": 555, "name": "未知之歌",
                                   "artists": ["某新人"], "duration_s": 200}])
    jobs = _scrobble_jobs([], listens, ncm)  # 库内为空
    result = Jobs._scrobble_recent(jobs)
    assert len(ncm.search_calls) == 1, "库内没有应走搜索"
    assert ncm.scrobble_calls == [(555, 200000)]
    assert result["ok"] is True and result["count"] == 1


def test_scrobble_slash_split_artist_matches_key(monkeypatch):
    """LB artist 是 '周杰伦/A-LNK'，库里首艺术家是'周杰伦' → 按 '/' 拆分命中 key。"""
    from app import jobs as jobs_mod
    lib_title, lib_ncm_id = "东风破", 77777
    lib_rows = [{"key": track_key(["周杰伦"], lib_title), "title": lib_title,
                 "ncm_id": lib_ncm_id, "status": "downloaded"}]
    listens = [{"listened_at": 1000, "artist": "周杰伦/A-LNK", "title": lib_title,
                "duration_ms": 260000}]
    monkeypatch.setattr(jobs_mod, "get_recent_listens",
                        lambda username, min_ts=0: listens)
    ncm = _RecNCM()
    jobs = _scrobble_jobs(lib_rows, listens, ncm)
    result = Jobs._scrobble_recent(jobs)
    assert ncm.search_calls == []
    assert ncm.scrobble_calls == [(lib_ncm_id, 260000)]
    assert result["ok"] is True and result["count"] == 1
