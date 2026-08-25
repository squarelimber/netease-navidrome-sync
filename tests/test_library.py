"""m3u8 生成与文件命名、Subsonic 歌单管理测试。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.library import SubsonicClient, display_name, write_m3u8
from app.sources.base import Track


def test_display_name():
    tr = Track(title="晴天", artists=["周杰伦"])
    assert display_name(tr) == "周杰伦 - 晴天"


def test_display_name_sanitized():
    tr = Track(title='a/b:c', artists=["X"])
    name = display_name(tr)
    assert "/" not in name and ":" not in name


def test_write_m3u8(tmp_path):
    tracks = [
        ({"title": "晴天", "artists": ["周杰伦"]}, "周杰伦 - 晴天.mp3"),
        ({"title": "Song", "artists": ["A", "B"]}, "A, B - Song.flac"),
    ]
    path = write_m3u8(tmp_path, "测试歌单", tracks)
    content = path.read_text(encoding="utf-8")
    lines = content.splitlines()
    assert lines[0] == "#EXTM3U"
    assert "#PLAYLIST:测试歌单" in lines[1]
    assert "周杰伦 - 晴天.mp3" in lines
    assert "A, B - Song.flac" in lines
    assert content.count("#EXTINF") == 2


class _FakeResp:
    def __init__(self, payload, status="ok"):
        self._payload = {"subsonic-response": {"status": status, **payload}}

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


def test_subsonic_norm():
    assert SubsonicClient._norm("网易云日推-2026-08-22") == "网易云日推-2026-08-22"
    assert SubsonicClient._norm("网易云日推-2026-08-22.m3u8") == "网易云日推-2026-08-22"
    assert SubsonicClient._norm("ListenBrainz-CF-2026-08-22.M3U") == "listenbrainz-cf-2026-08-22"


def test_subsonic_list_playlists(monkeypatch):
    c = SubsonicClient("http://mock", "u", "p")
    calls = {}

    def fake_get(url, params=None, timeout=None):
        calls["url"] = url
        return _FakeResp({"playlist": {"children": [
            {"id": "1", "name": "网易云日推-2026-08-22"},
            {"id": "2", "name": "Weekly Jams"},
        ]}})

    monkeypatch.setattr("app.library.requests.get", fake_get)
    pls = c.list_playlists()
    assert calls["url"].endswith("/rest/getPlaylists.view")
    assert [p["id"] for p in pls] == ["1", "2"]


def test_subsonic_list_playlists_error(monkeypatch):
    c = SubsonicClient("http://mock", "u", "p")
    monkeypatch.setattr("app.library.requests.get",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    assert c.list_playlists() == []


def test_subsonic_delete_playlist(monkeypatch):
    c = SubsonicClient("http://mock", "u", "p")
    calls = {}

    def fake_get(url, params=None, timeout=None):
        calls["params"] = params
        return _FakeResp({})

    monkeypatch.setattr("app.library.requests.get", fake_get)
    assert c.delete_playlist("1") is True
    assert calls["params"]["id"] == "1"

    def fake_get_err(url, params=None, timeout=None):
        return _FakeResp({}, status="error")

    monkeypatch.setattr("app.library.requests.get", fake_get_err)
    assert c.delete_playlist("1") is False
