"""matcher 与 util 的归一化/匹配测试。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import matcher
from app.sources.base import Track
from app.util import normalize, safe_name, track_key


def t(title, artists, duration_ms=0):
    return Track(title=title, artists=artists, duration_ms=duration_ms)


class TestNormalize:
    def test_basic(self):
        assert normalize("Hello World") == "hello world"

    def test_strip_brackets(self):
        assert normalize("起风了（Live）") == "起风了"
        assert normalize("Song (2020 Remaster)") == "song"

    def test_strip_feat(self):
        assert normalize("Stay feat. Someone") == "stay"

    def test_track_key(self):
        assert track_key(["Jay Chou"], "晴天") == track_key(["jay chou"], "晴天")
        assert track_key(["A"], "B") != track_key(["A"], "C")

    def test_t2s_conversion(self):
        assert normalize("周杰倫") == normalize("周杰伦")
        assert normalize("陳奕迅 淘汰") == normalize("陈奕迅 淘汰")
        assert track_key(["周杰倫"], "红尘客栈") == track_key(["周杰伦"], "红尘客栈")

    def test_t2s_matcher(self):
        track = t("淘汰", ["陳奕迅"])
        cand = {"name": "淘汰", "artists": ["陈奕迅"]}
        assert matcher.is_match(track, cand)


class TestMatcher:
    def test_exact_match(self):
        track = t("晴天", ["周杰伦"], 269000)
        cand = {"name": "晴天", "artists": ["周杰伦"], "duration": 269}
        assert matcher.is_match(track, cand)

    def test_title_too_different(self):
        track = t("晴天", ["周杰伦"])
        cand = {"name": "雨天", "artists": ["周杰伦"]}
        assert not matcher.is_match(track, cand)

    def test_artist_mismatch(self):
        track = t("晴天", ["周杰伦"])
        cand = {"name": "晴天", "artists": ["别人"]}
        assert not matcher.is_match(track, cand)

    def test_multi_artist_one_hit(self):
        track = t("珊瑚海", ["周杰伦", "梁心颐"])
        cand = {"name": "珊瑚海", "artists": ["周杰伦", "梁心颐"]}
        assert matcher.is_match(track, cand)

    def test_duration_tolerance(self):
        track = t("Song", ["Artist"], 200000)
        ok = {"name": "Song", "artists": ["Artist"], "duration": 210}
        bad = {"name": "Song", "artists": ["Artist"], "duration": 300}
        assert matcher.is_match(track, ok, max_duration_diff=12)
        assert not matcher.is_match(track, bad, max_duration_diff=12)

    def test_duration_missing_passes(self):
        track = t("Song", ["Artist"], 200000)
        cand = {"name": "Song", "artists": ["Artist"]}
        assert matcher.is_match(track, cand)

    def test_best_match_picks_closest(self):
        track = t("晴天", ["周杰伦"])
        cands = [
            {"name": "晴天 (Cover)", "artists": ["周杰伦"]},
            {"name": "晴天", "artists": ["周杰伦"]},
        ]
        best = matcher.best_match(track, cands)
        assert best["name"] == "晴天"

    def test_best_match_none(self):
        track = t("不存在的歌xyz", [" nobody"])
        assert matcher.best_match(track, []) is None


class TestSafeName:
    def test_illegal_chars(self):
        assert "/" not in safe_name("AC/DC")
        assert ":" not in safe_name("a:b")

    def test_not_empty(self):
        assert safe_name("???") != ""
