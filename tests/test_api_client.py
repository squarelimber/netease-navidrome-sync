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
    # params 是 base64（双层 AES 输出）
    decoded = base64.b64decode(out["params"], validate=True)
    assert len(decoded) % 16 == 0 and len(decoded) >= 16
    # encSecKey 是 RSA-1024 原始密文 → 128 字节 hex → 256 字符小写
    assert len(out["encSecKey"]) == 256
    assert out["encSecKey"] == out["encSecKey"].lower()
    int(out["encSecKey"], 16)  # 合法十六进制


def test_weapi_encrypt_golden_vector():
    # 黄金向量：按参考实现（NeteaseCloudMusicApi util/crypto.js）生成，
    # 已验证可被真实服务器解密（music.163.com /weapi/playlist/detail 返回 200）。
    out = _weapi_encrypt(
        {"logs": "x"},
        cookie="MUSIC_U=abc; _csrf=TESTCSRF123; other=1",
        _secret_key="Ab3dEf6hIj9kLmNo",
    )
    assert out["params"] == (
        "LoCV0Admo53fklCQxXtxfA3yYJhX26xZwcwDs4RXSouCBu2Mb+etXg2BzVDqSC9E7zwMn3swtnqiYNkiqijMsHO8wxxBZuQOi26TpOVp9UI="
    )
    assert out["encSecKey"] == (
        "c387709a0ac2b5841e633a02d21251a17504ba87489812a6c3a2e9d89860e46d"
        "e9b2ccf9952a97df2cc32c407156fbb54b96af51d3c3c3d92aeb1b0931bccf00"
        "6216d32665685d0f1de817d13d03639582a6b40540d55b5a476261a6a56419fb"
        "cfed6cb5d97f103ead3d8f30df3181c3715beb5a942e0e25ca63d1a66bf68dc4"
    )


def test_weapi_encrypt_csrf_token_in_plaintext():
    # csrf_token 进入明文：Cookie 有无 _csrf 时密文必须不同
    a = _weapi_encrypt({"logs": "x"}, cookie="", _secret_key="Ab3dEf6hIj9kLmNo")
    b = _weapi_encrypt({"logs": "x"}, cookie="_csrf=TESTCSRF123", _secret_key="Ab3dEf6hIj9kLmNo")
    assert a["params"] == "LoCV0Admo53fklCQxXtxfN8u1rdA0GytGoQACyU98kUKNeB/zHNhOgumvRM0REHD"
    assert a["params"] != b["params"]
    assert a["encSecKey"] == b["encSecKey"]  # 同一 secret key → 同一 encSecKey


def test_scrobble_direct_posts_music163(monkeypatch):
    posts = []

    class _Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"code": 200}

    def fake_post(url, data=None, headers=None, timeout=None):
        posts.append({"url": url, "data": data, "headers": headers})
        return _Resp()

    monkeypatch.setattr("app.api_client.time.sleep", lambda _: None)
    c = NCMAPIClient("http://mock")
    c._cookie = "MUSIC_U=abc; _csrf=CSRF123"
    c.session.post = fake_post
    assert c._scrobble_direct(123, 180000) is True
    # 完整打卡 = startplay + playend 两次 weapi 请求
    assert len(posts) == 2
    for p in posts:
        assert p["url"] == "https://music.163.com/weapi/feedback/weblog"
        assert p["headers"]["Cookie"] == "MUSIC_U=abc; _csrf=CSRF123"
        assert set(p["data"]) == {"params", "encSecKey"}
        base64.b64decode(p["data"]["params"], validate=True)  # 合法 base64 密文


def test_scrobble_direct_payload_structure(monkeypatch):
    """startplay + playend 两条，playend 带 mainsite 字段且 time 用秒。"""
    monkeypatch.setattr("app.api_client.time.sleep", lambda _: None)
    captured = []

    def fake_weblog(logs_obj):
        captured.append(logs_obj)
        return True

    c = NCMAPIClient("http://mock")
    c._cookie = "MUSIC_U=abc"
    c._weblog_post = fake_weblog
    assert c._scrobble_direct(3387791686, 196821) is True
    assert len(captured) == 2
    start, play = captured
    # startplay
    assert start[0]["action"] == "startplay"
    assert start[0]["json"]["id"] == "3387791686"
    assert start[0]["json"]["mainsite"] == "1"
    assert start[0]["json"]["mainsiteWeb"] == "1"
    assert start[0]["json"]["content"] == "id=3387791686"
    # playend：time 用秒（196821ms -> 196s），带 mainsite 字段
    assert play[0]["action"] == "play"
    assert play[0]["json"]["end"] == "playend"
    assert play[0]["json"]["time"] == 196
    assert play[0]["json"]["mainsite"] == "1"
    assert play[0]["json"]["mainsiteWeb"] == "1"
    assert play[0]["json"]["content"] == "id=3387791686"
    assert play[0]["json"]["source"] == "list"


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


# ---- 最近播放（ncm-api /record/recent/song 方案）----

def test_recent_songs_via_record():
    def fake_get(path, **params):
        assert path == "/record/recent/song"
        assert params["limit"] == 100
        return {"code": 200, "data": {"total": 1, "list": [
            {"id": 1, "name": "晴天", "ar": [{"name": "周杰伦"}],
             "al": {"name": "叶惠美"}, "dt": 269000, "time": 1700000000000},
        ]}, "message": ""}

    c = _client(fake_get)
    songs = c.recent_songs(100)
    assert len(songs) == 1
    assert songs[0]["id"] == 1
    assert songs[0]["title"] == "晴天"
    assert songs[0]["artists"] == ["周杰伦"]
    assert songs[0]["album"] == "叶惠美"
    assert songs[0]["duration_ms"] == 269000
    assert songs[0]["time"] == 1700000000  # 毫秒 → 秒


def test_recent_songs_wrapped_song():
    """条目被 {song:{...}} 包裹时也能解析。"""
    def fake_get(path, **params):
        return {"code": 200, "data": {"total": 1, "list": [
            {"song": {"id": 2, "name": "夜曲", "artists": [{"name": "周杰伦"}],
                      "album": {"name": "十一月的萧邦"}, "duration": 227000},
             "time": 1700000123},
        ]}}

    c = _client(fake_get)
    songs = c.recent_songs(10)
    assert songs[0]["id"] == 2
    assert songs[0]["title"] == "夜曲"
    assert songs[0]["artists"] == ["周杰伦"]
    assert songs[0]["album"] == "十一月的萧邦"
    assert songs[0]["duration_ms"] == 227000
    assert songs[0]["time"] == 1700000123


def test_recent_songs_real_structure():
    """线上真实结构：{resourceId, playTime, resourceType, data:{歌曲}, banned, multiTerminalInfo}。"""
    def fake_get(path, **params):
        return {"code": 200, "data": {"total": 1, "list": [
            {"resourceId": 3, "playTime": 1700000456000, "resourceType": "song",
             "data": {"id": 3, "name": "青花瓷", "ar": [{"name": "周杰伦"}],
                      "al": {"name": "我很忙"}, "dt": 231000},
             "banned": False, "multiTerminalInfo": {}},
        ]}}

    c = _client(fake_get)
    songs = c.recent_songs(10)
    assert songs[0]["id"] == 3
    assert songs[0]["title"] == "青花瓷"
    assert songs[0]["artists"] == ["周杰伦"]
    assert songs[0]["album"] == "我很忙"
    assert songs[0]["duration_ms"] == 231000
    assert songs[0]["time"] == 1700000456  # playTime 毫秒 → 秒


def test_recent_songs_empty_list():
    c = _client(lambda path, **params: {"code": 200, "data": {"total": 0, "list": []}})
    assert c.recent_songs(100) == []


def test_recent_songs_error_code_raises():
    c = _client(lambda path, **params: {"code": 301, "message": "未登录"})
    try:
        c.recent_songs()
        assert False, "code!=200 应抛异常"
    except RuntimeError as e:
        assert "code=301" in str(e)


def test_recent_songs_request_error_raises():
    c = _client(lambda path, **params: {"_request_error": True})
    try:
        c.recent_songs()
        assert False, "请求错误应抛异常"
    except RuntimeError as e:
        assert "ncm-api" in str(e)


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


def test_custom_music_host_used_in_scrobble_urls(monkeypatch):
    monkeypatch.setattr("app.api_client.time.sleep", lambda _: None)

    class _Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"code": 200}

    c = NCMAPIClient("http://mock", music_host="http://192.168.0.120:3000")
    c._cookie = "MUSIC_U=abc"
    urls = []

    def fake_post(url, data=None, headers=None, timeout=None):
        urls.append(url)
        return _Resp()

    c.session.post = fake_post
    assert c._scrobble_direct(123, 180000) is True
    # startplay + playend 两次，都走自定义 music_host
    assert urls == [
        "http://192.168.0.120:3000/weapi/feedback/weblog",
        "http://192.168.0.120:3000/weapi/feedback/weblog",
    ]
