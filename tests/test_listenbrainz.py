"""ListenBrainz JSPF 解析测试（纯离线，不依赖网络）。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.sources.listenbrainz import _jspf_artist, _jspf_mbid


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