"""歌词合并与聚合逻辑测试。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.jobs import _merge_lrc
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


def test_aggregate_dedup():
    """验证推荐聚合去重逻辑（与 jobs.daily_run 内一致）。"""
    tracks = [
        Track(title="晴天", artists=["周杰伦"], origin="netease_daily", score=1.0),
        Track(title="晴天", artists=["周杰伦"], origin="lastfm", score=0.5),
        Track(title="Song", artists=["A"], origin="lastfm", score=0.8),
    ]
    merged = {}
    for t in tracks:
        k = track_key(t.artists, t.title)
        if k in merged:
            old = merged[k]
            old.score = max(old.score, t.score) + 0.1
            old.origin = f"{old.origin},{t.origin}" if t.origin not in old.origin else old.origin
        else:
            merged[k] = t
    assert len(merged) == 2
    dup = merged[track_key(["周杰伦"], "晴天")]
    assert dup.score == 1.1
    assert "netease_daily" in dup.origin and "lastfm" in dup.origin
