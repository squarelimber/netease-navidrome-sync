"""NCMAPIClient 分批/分页接口测试。"""

import base64
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.api_client import NCMAPIClient, _weapi_encrypt


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


def test_scrobble_retries_transient_502(monkeypatch):
    calls = []

    def fake_get(path, **params):
        calls.append(path)
        if len(calls) == 1:
            return {"code": -1, "_request_error": True, "_http_status": 502}
        return {"code": 200}

    c = _client(fake_get)
    monkeypatch.setattr("app.api_client.time.sleep", lambda _: None)
    assert c.scrobble(123) is True
    assert calls == ["/scrobble", "/scrobble"]


def test_search_retries_rate_limit_405(monkeypatch):
    calls = []

    def fake_get(path, **params):
        calls.append(path)
        if len(calls) == 1:
            return {"code": -1, "_request_error": True, "_http_status": 405,
                    "_error_snippet": '{"code":405,"msg":"操作频繁，请稍候再试"}'}
        return {"code": 200, "result": {"songs": [_song(1)]}}

    c = _client(fake_get)
    monkeypatch.setattr("app.api_client.time.sleep", lambda _: None)
    assert c.search("晴天", limit=5)[0]["id"] == 1
    assert calls == ["/cloudsearch", "/cloudsearch"]


# ---- weapi 直连 scrobble ----

def test_weapi_encrypt_structure():
    out = _weapi_encrypt({"logs": "x"})
    # param 是 base64（双层 AES 输出）
    base64.b64decode(out["param"], validate=True)
    # encSecKey 是 RSA-1024 → 128 字节 hex → 256 字符大写
    assert len(out["encSecKey"]) == 256
    assert out["encSecKey"] == out["encSecKey"].upper()
    int(out["encSecKey"], 16)  # 合法十六进制


def test_scrobble_direct_posts_music163():
    import app.api_client as m
    calls = {}

    class _Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"code": 200}

    def fake_post(url, data=None, headers=None, timeout=None):
        calls["url"] = url
        calls["data"] = data
        calls["headers"] = headers
        return _Resp()

    c = NCMAPIClient("http://mock")
    c._cookie = "MUSIC_U=abc"
    c.session.post = fake_post
    assert c._scrobble_direct(123, 180000) is True
    assert calls["url"] == "https://music.163.com/api/feedback/weblog"
    assert calls["headers"]["Cookie"] == "MUSIC_U=abc"
    assert set(calls["data"]) == {"param", "encSecKey"}
    base64.b64decode(calls["data"]["param"], validate=True)  # param 为合法 base64 密文


def test_scrobble_prefers_direct_when_cookie_set():
    c = NCMAPIClient("http://mock")
    c._cookie = "MUSIC_U=abc"
    direct = []

    def fake_direct(song_id, time_ms):
        direct.append(song_id)
        return True

    c._scrobble_direct = fake_direct
    c._scrobble_via_ncm = lambda sid, t: (_ for _ in ()).throw(AssertionError("ncm 不应被调用"))
    assert c.scrobble(456) is True
    assert direct == [456]


def test_scrobble_falls_back_to_ncm_without_cookie():
    c = NCMAPIClient("http://mock")
    # 无 Cookie → 直连被跳过，走 ncm-api 路径
    ncm = []

    def fake_get(path, **params):
        ncm.append(path)
        return {"code": 200}

    c._get = fake_get
    assert c.scrobble(456) is True
    assert ncm == ["/scrobble"]


# ---- 最近播放 ----

def test_recent_songs_parses_list():
    class _Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"code": 200, "list": [
                {"song": {"id": 1, "name": "晴天", "artists": [{"name": "周杰伦"}],
                          "album": {"name": "叶惠美"}, "duration": 269000},
                 "time": 1750000000000},  # 毫秒时间戳
                {"song": {"id": 2, "name": "夜曲", "artists": [{"name": "周杰伦"}],
                          "album": {"name": "x"}, "duration": 238000},
                 "time": 1750000100},  # 秒时间戳
            ]}

    c = NCMAPIClient("http://mock")
    c._cookie = "MUSIC_U=abc"
    c.session.post = lambda url, data=None, headers=None, timeout=None: _Resp()
    songs = c.recent_songs(50)
    assert [s["id"] for s in songs] == [1, 2]
    assert songs[0]["title"] == "晴天"
    assert songs[0]["artists"] == ["周杰伦"]
    assert songs[0]["duration_ms"] == 269000
    assert songs[0]["time"] == 1750000000  # 毫秒 → 秒
    assert songs[1]["time"] == 1750000100


def test_recent_songs_requires_cookie():
    c = NCMAPIClient("http://mock")
    try:
        c.recent_songs()
        assert False, "无 Cookie 应抛异常"
    except RuntimeError as e:
        assert "Cookie" in str(e)


def test_recent_songs_error_code_raises():
    class _Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"code": 301}

    c = NCMAPIClient("http://mock")
    c._cookie = "MUSIC_U=abc"
    c.session.post = lambda url, data=None, headers=None, timeout=None: _Resp()
    try:
        c.recent_songs()
        assert False, "非 200 code 应抛异常"
    except RuntimeError as e:
        assert "301" in str(e)


# ---- ncm_music_host 直连开关 ----

def test_empty_music_host_disables_direct_scrobble():
    c = NCMAPIClient("http://mock", music_host="")
    c._cookie = "MUSIC_U=abc"
    ncm = []

    def fake_get(path, **params):
        ncm.append(path)
        return {"code": 200}

    c._get = fake_get
    assert c.scrobble(123) is True
    assert ncm == ["/scrobble"]  # 直连被禁用，直接走 ncm-api


def test_empty_music_host_disables_recent_songs():
    c = NCMAPIClient("http://mock", music_host="")
    c._cookie = "MUSIC_U=abc"
    try:
        c.recent_songs()
        assert False, "直连禁用时应抛异常"
    except RuntimeError as e:
        assert "禁用" in str(e)


def test_custom_music_host_used_in_urls():
    class _Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"code": 200, "list": []}

    c = NCMAPIClient("http://mock", music_host="http://192.168.0.120:3000")
    c._cookie = "MUSIC_U=abc"
    urls = []

    def fake_post(url, data=None, headers=None, timeout=None):
        urls.append(url)
        return _Resp()

    c.session.post = fake_post
    c.recent_songs(10)
    assert urls == ["http://192.168.0.120:3000/api/song/list/recent"]
