"""m3u8 生成与文件命名测试。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.library import display_name, write_m3u8
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
