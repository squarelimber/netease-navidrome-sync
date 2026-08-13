"""yt-dlp 兜底源测试。"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.downloader import MusicDLEngine
from app.sources.base import Track


def _track(title="晴天", artists=None, duration_ms=260000):
    return Track(title=title, artists=artists or ["周杰伦"], duration_ms=duration_ms)


class _FakeProc:
    def __init__(self, returncode, stdout, stderr):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _engine(tmp_path):
    return MusicDLEngine(["ytdlp"], tmp_path / "work")


def test_pick_exact_with_artist(tmp_path):
    e = _engine(tmp_path)
    entries = [
        {"id": "a", "title": "周杰伦 - 晴天 (Official Video)", "duration": 260},
        {"id": "b", "title": "某翻唱 - 晴天", "duration": 260},
    ]
    hit = e._pick_ytdlp_candidate(_track(), entries)
    assert hit["id"] == "a"


def test_pick_rejects_artist_mismatch(tmp_path):
    e = _engine(tmp_path)
    entries = [{"id": "a", "title": "路人甲 - 晴天", "duration": 260}]
    assert e._pick_ytdlp_candidate(_track(), entries) is None


def test_pick_rejects_duration_mismatch(tmp_path):
    e = _engine(tmp_path)
    entries = [{"id": "a", "title": "周杰伦 - 晴天", "duration": 120}]
    assert e._pick_ytdlp_candidate(_track(), entries) is None


def test_pick_title_only_when_no_separator(tmp_path):
    e = _engine(tmp_path)
    entries = [{"id": "a", "title": "晴天 周杰伦 无损纯享", "duration": 260}]
    assert e._pick_ytdlp_candidate(_track(), entries) is not None


def test_pick_empty_entries(tmp_path):
    e = _engine(tmp_path)
    assert e._pick_ytdlp_candidate(_track(), []) is None


def test_download_ytdlp_flow(tmp_path, monkeypatch):
    e = _engine(tmp_path)

    def fake_run(args, timeout=240):
        if "-J" in args and "--flat-playlist" in args:
            payload = {"entries": [
                {"id": "VIDEO1", "title": "周杰伦 - 晴天 (Official)", "duration": 260},
            ]}
            return _FakeProc(0, json.dumps(payload), "")
        if "-f" in args:
            vid = [a.split("=")[1] for a in args if a.startswith("https://")][0]
            out = tmp_path / "work" / "ytdlp" / f"{vid}.m4a"
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(b"z" * 200 * 1024)
            return _FakeProc(0, "", "")
        return _FakeProc(1, "", "boom")

    monkeypatch.setattr(MusicDLEngine, "_run_ytdlp", staticmethod(fake_run))
    path = e._download_ytdlp(_track())
    assert path is not None and path.name == "VIDEO1.m4a"


def test_download_ytdlp_search_failed(tmp_path, monkeypatch):
    e = _engine(tmp_path)
    monkeypatch.setattr(MusicDLEngine, "_run_ytdlp",
                        staticmethod(lambda args, timeout=240: _FakeProc(1, "", "err")))
    assert e._download_ytdlp(_track()) is None


def test_engine_chain_uses_ytdlp(tmp_path, monkeypatch):
    e = MusicDLEngine(["netease", "ytdlp"], tmp_path / "w")
    fake_path = tmp_path / "w" / "x.mp3"

    def fake_download(track, source):
        return fake_path if source == "ytdlp" else None

    monkeypatch.setattr(e, "_download_from_source", fake_download)
    path, src = e.download(_track())
    assert src == "ytdlp"
    assert path == fake_path
