"""网易云歌单翻页与兜底测试。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.sources.netease_playlist import NeteasePlaylistSource


def _song(i):
    return {"id": i, "name": f"s{i}", "artists": ["a"], "album": "",
            "duration_ms": 1000}


def test_playlist_paging(tmp_path):
    class FakeAPI:
        def playlist_track_all(self, pid, limit=1000, offset=0):
            if offset >= 1200:
                return []
            return [_song(offset + i)
                    for i in range(min(limit, 1200 - offset))]

        def playlist_detail(self, pid):
            return {}

    src = NeteasePlaylistSource(FakeAPI(), [{"id": 1, "name": "p"}])
    tracks = src.fetch()
    assert len(tracks) == 1200
    assert tracks[0].playlist == "p"
    assert tracks[1199].ncm_id == 1199


def test_playlist_fallback_to_detail(tmp_path):
    class FakeAPI:
        def playlist_track_all(self, pid, limit=1000, offset=0):
            return []

        def playlist_detail(self, pid):
            return {"track_ids": [1, 2, 3]}

        def song_detail(self, ids):
            return [_song(i) for i in ids]

    src = NeteasePlaylistSource(FakeAPI(), [{"id": 1, "name": "p"}])
    tracks = src.fetch()
    assert [t.ncm_id for t in tracks] == [1, 2, 3]


def test_playlist_dedup_overlapping_pages(tmp_path):
    class FakeAPI:
        def playlist_track_all(self, pid, limit=1000, offset=0):
            if offset == 0:
                return [_song(i) for i in range(1000)]
            if offset == 1000:
                return [_song(i) for i in range(500, 1500)]  # 与上一页重叠 500 首
            return []

        def playlist_detail(self, pid):
            return {}

    src = NeteasePlaylistSource(FakeAPI(), [{"id": 1, "name": "p"}])
    tracks = src.fetch()
    assert len(tracks) == 1500
    assert len({t.ncm_id for t in tracks}) == 1500
