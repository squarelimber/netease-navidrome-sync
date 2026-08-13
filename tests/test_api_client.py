"""NCMAPIClient 分批/分页接口测试。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.api_client import NCMAPIClient


def _client(handler) -> NCMAPIClient:
    c = NCMAPIClient("http://mock")
    c._get = handler
    return c


def _song(i):
    return {"id": i, "name": f"s{i}", "ar": [{"name": "a"}],
            "al": {"name": "al", "picUrl": ""}, "dt": 1000}


def test_song_detail_chunks_ids():
    calls = []

    def fake_get(path, **params):
        calls.append((path, params["ids"]))
        ids = [int(x) for x in params["ids"].split(",")]
        return {"code": 200, "songs": [_song(i) for i in ids]}

    c = _client(fake_get)
    songs = c.song_detail(list(range(450)))
    assert len(songs) == 450
    assert len(calls) == 3  # 200 + 200 + 50
    assert len(calls[2][1].split(",")) == 50


def test_song_detail_partial_failure_keeps_others():
    def fake_get(path, **params):
        if params["ids"].startswith("0"):
            return {"code": -1}
        ids = [int(x) for x in params["ids"].split(",")]
        return {"code": 200, "songs": [_song(i) for i in ids]}

    c = _client(fake_get)
    songs = c.song_detail(list(range(250)))
    assert len(songs) == 50  # 第二批次 200-249


def test_playlist_track_all():
    def fake_get(path, **params):
        assert path == "/playlist/track/all"
        assert params["limit"] == 1000 and params["offset"] == 0
        return {"code": 200, "songs": [_song(1)]}

    c = _client(fake_get)
    songs = c.playlist_track_all(123, limit=1000, offset=0)
    assert songs[0]["id"] == 1


def test_playlist_track_all_error_returns_empty():
    c = _client(lambda path, **params: {"code": -1})
    assert c.playlist_track_all(1) == []
