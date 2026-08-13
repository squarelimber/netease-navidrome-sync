"""MusicDLEngine 热更新与临时清理测试。"""

import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.downloader import MusicDLEngine


def test_update_config_resets_clients(tmp_path):
    e = MusicDLEngine(["netease"], tmp_path / "work", interval=2.0)
    e._clients["netease"] = object()
    e.update_config(sources=["kuwo"], title_threshold=80,
                    max_duration_diff=20, interval=0.5)
    assert e.sources == ["kuwo"]
    assert e.title_threshold == 80
    assert e.max_duration_diff == 20
    assert e._clients == {}


def test_update_config_filters_unknown_sources(tmp_path):
    e = MusicDLEngine(["netease"], tmp_path / "work")
    e.update_config(sources=["qq", "bogus"])
    assert e.sources == ["qq"]


def test_set_netease_cookie_drops_cached_client(tmp_path):
    e = MusicDLEngine(["netease", "kuwo"], tmp_path / "work")
    e._clients["netease"] = object()
    e._clients["kuwo"] = object()
    e.set_netease_cookie("MUSIC_U=abc")
    assert e.netease_cookie == "MUSIC_U=abc"
    assert "netease" not in e._clients
    assert "kuwo" in e._clients


def test_cleanup_removes_stale_files_only(tmp_path):
    e = MusicDLEngine(["netease"], tmp_path / "work")
    fresh = e.work_dir / "fresh.bin"
    fresh.write_bytes(b"x")
    stale = e.work_dir / "stale.bin"
    stale.write_bytes(b"x")
    old = time.time() - 2 * 86400
    os.utime(stale, (old, old))
    e.cleanup(max_age_s=86400)
    assert fresh.exists()
    assert not stale.exists()
