"""ListenBrainz JSPF 解析测试（纯离线，不依赖网络）。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.sources.listenbrainz import ListenBrainzSource, _jspf_artist, _jspf_mbid


def test_artist_string():
    t = {"creator": "周杰伦"}
    assert _jspf_artist(t) == ["周杰伦"]


def test_artist_dict():
    t = {"creator": {"name": "Beyond"}}
    assert _jspf_artist(t) == ["Beyond"]


def test_artist_extension_fallback():
    t = {"creator": None,
         "extension": {"https://musicbrainz.org/doc/jspf#playlist": {"artist": "A"}}}
    assert _jspf_artist(t) == ["A"]


def test_artist_missing():
    assert _jspf_artist({}) == []


def test_mbid_from_identifier():
    t = {"identifier": "https://musicbrainz.org/recording/abc-123"}
    assert _jspf_mbid(t) == "abc-123"


def test_mbid_missing():
    assert _jspf_mbid({}) == ""


def test_get_accepts_params():
    """回归：_get 必须透传 params（CF 推荐依赖该参数）。"""
    src = ListenBrainzSource("user")
    captured = {}

    class FakeSession:
        def get(self, url, timeout=None, **kwargs):
            captured["url"] = url
            captured["kwargs"] = kwargs
            return object()

    src.session = FakeSession()
    src._get("http://mock", params={"count": 30})
    assert captured["url"] == "http://mock"
    assert captured["kwargs"]["params"] == {"count": 30}


def test_cf_recs_passes_params():
    """回归：_cf_recs 用 params 传 count，不再抛 TypeError。"""
    src = ListenBrainzSource("user", cf_count=30, use_mb=True)
    calls = []

    class Resp:
        status_code = 200

        def json(self):
            return {"payload": {"mbids": []}}

    def fake_get(url, timeout=20, **kwargs):
        calls.append((url, kwargs))
        return Resp()

    src._get = fake_get
    src._cf_recs()
    assert calls and calls[0][1].get("params", {}).get("count") == 30