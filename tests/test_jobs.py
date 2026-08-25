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


def test_cleanup_no_candidates_skips_api(tmp_path):
    sub = _FakeSubsonic([{"id": "1", "name": "whatever"}])
    db = _FakeDB(set())
    fn = _cleanup_fn(tmp_path, db, sub)()

    assert getattr(sub, "listed", False) is False  # 无过期歌单时不调用 API
    assert db.deleted == []
