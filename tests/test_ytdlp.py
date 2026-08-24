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

    def fake_run(args, timeout=240, **kwargs):
        if "ytsearch" in " ".join(args):
            payload = {"entries": [
                {"id": "VIDEO1", "title": "周杰伦 - 晴天 (Official)", "duration": 260},
            ]}
            return _FakeProc(0, json.dumps(payload), "")
        if "-J" in args and "https://www.youtube.com/watch?v=VIDEO1" in args:
            payload = {"formats": [{
                "format_id": "140", "ext": "m4a", "vcodec": "none",
                "acodec": "mp4a.40.2", "abr": 129, "protocol": "https",
                "url": "https://example.test/audio",
            }]}
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
                        staticmethod(lambda args, timeout=240, **kwargs: _FakeProc(1, "", "err")))
    assert e._download_ytdlp(_track()) is None


def test_check_ytdlp_cookie_missing(tmp_path):
    e = MusicDLEngine(["ytdlp"], tmp_path / "work", ytdlp_cookies=tmp_path / "missing.txt")
    result = e.check_ytdlp_cookie()
    assert result["state"] == "missing"
    assert result["ok"] is False


def test_check_ytdlp_cookie_valid(tmp_path, monkeypatch):
    cookie = tmp_path / "cookies.txt"
    cookie.write_text("# Netscape HTTP Cookie File\n", encoding="utf-8")
    e = MusicDLEngine(["ytdlp"], tmp_path / "work", ytdlp_cookies=cookie)
    monkeypatch.setattr(MusicDLEngine, "_run_ytdlp",
                        staticmethod(lambda args, timeout=60, **kwargs: _FakeProc(0, "{}", "")))
    result = e.check_ytdlp_cookie()
    assert result["state"] == "valid"
    assert result["ok"] is True


def test_check_ytdlp_cookie_invalid_is_distinguished(tmp_path, monkeypatch):
    cookie = tmp_path / "cookies.txt"
    cookie.write_text("# Netscape HTTP Cookie File\n", encoding="utf-8")
    e = MusicDLEngine(["ytdlp"], tmp_path / "work", ytdlp_cookies=cookie)
    monkeypatch.setattr(MusicDLEngine, "_run_ytdlp",
                        staticmethod(lambda args, timeout=60, **kwargs: _FakeProc(
                            1, "", "The provided YouTube account cookies are no longer valid")))
    result = e.check_ytdlp_cookie()
    assert result["state"] == "invalid"
    assert result["ok"] is False


def test_check_ytdlp_cookie_403_is_unknown(tmp_path, monkeypatch):
    cookie = tmp_path / "cookies.txt"
    cookie.write_text("# Netscape HTTP Cookie File\n", encoding="utf-8")
    e = MusicDLEngine(["ytdlp"], tmp_path / "work", ytdlp_cookies=cookie)
    monkeypatch.setattr(MusicDLEngine, "_run_ytdlp",
                        staticmethod(lambda args, timeout=60, **kwargs: _FakeProc(1, "", "HTTP Error 403")))
    result = e.check_ytdlp_cookie()
    assert result["state"] == "unknown"
    assert result["ok"] is None


def test_download_chooses_mode_with_m4a(tmp_path, monkeypatch):
    cookie = tmp_path / "cookies.txt"
    cookie.write_text("# Netscape HTTP Cookie File\n", encoding="utf-8")
    e = MusicDLEngine(["ytdlp"], tmp_path / "work", ytdlp_cookies=cookie)
    calls = []

    def fake_run(args, timeout=240, **kwargs):
        calls.append((args, kwargs))
        if "ytsearch" in " ".join(args):
            return _FakeProc(0, json.dumps({"entries": [
                {"id": "VIDEO2", "title": "周杰伦 - 晴天", "duration": 260},
            ]}), "")
        if "-J" in args:
            if kwargs.get("use_cookies"):
                payload = {"formats": [{
                    "format_id": "140", "ext": "m4a", "vcodec": "none",
                    "acodec": "mp4a.40.2", "abr": 129, "protocol": "https",
                    "url": "https://example.test/cookie-audio",
                }]}
            else:
                payload = {"formats": [{
                    "format_id": "18", "ext": "mp4", "vcodec": "avc1",
                    "acodec": "mp4a.40.2", "abr": 143, "protocol": "https",
                    "url": "https://example.test/video",
                }]}
            return _FakeProc(0, json.dumps(payload), "")
        if "-f" in args:
            assert "140" in args
            out = tmp_path / "work" / "ytdlp" / "VIDEO2.m4a"
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(b"z" * 200 * 1024)
            return _FakeProc(0, "", "")
        return _FakeProc(1, "", "boom")

    monkeypatch.setattr(MusicDLEngine, "_run_ytdlp", staticmethod(fake_run))
    path = e._download_ytdlp(_track())
    assert path is not None and path.name == "VIDEO2.m4a"
    download_calls = [c for c in calls if "-f" in c[0]]
    assert download_calls and download_calls[0][1]["use_cookies"] is True


def test_cookie_probe_failed_skips_anonymous_fallback(tmp_path, monkeypatch):
    """Cookie 模式探测无可用音频格式时，不再回退匿名下载（匿名必然 403）。"""
    cookie = tmp_path / "cookies.txt"
    cookie.write_text("# Netscape HTTP Cookie File\n", encoding="utf-8")
    e = MusicDLEngine(["ytdlp"], tmp_path / "work", ytdlp_cookies=cookie)
    calls = []

    def fake_run(args, timeout=240, **kwargs):
        calls.append((args, kwargs))
        if "ytsearch" in " ".join(args):
            return _FakeProc(0, json.dumps({"entries": [
                {"id": "VIDEO3", "title": "周杰伦 - 晴天", "duration": 260},
            ]}), "")
        if "-J" in args:
            if kwargs.get("use_cookies"):
                # Cookie 模式：无可用音频格式（Cookie 失效/账号被风控的典型现象）
                return _FakeProc(0, json.dumps({"formats": []}), "")
            return _FakeProc(0, json.dumps({"formats": [{
                "format_id": "140", "ext": "m4a", "vcodec": "none",
                "acodec": "mp4a.40.2", "abr": 129, "protocol": "https",
                "url": "https://example.test/audio",
            }]}), "")
        return _FakeProc(1, "", "boom")

    monkeypatch.setattr(MusicDLEngine, "_run_ytdlp", staticmethod(fake_run))
    path = e._download_ytdlp(_track())
    assert path is None
    assert not any("-f" in c[0] for c in calls), "不应再发起匿名下载"


def test_engine_chain_uses_ytdlp(tmp_path, monkeypatch):
    e = MusicDLEngine(["netease", "ytdlp"], tmp_path / "w")
    fake_path = tmp_path / "w" / "x.mp3"

    def fake_download(track, source):
        return fake_path if source == "ytdlp" else None

    monkeypatch.setattr(e, "_download_from_source", fake_download)
    path, src = e.download(_track())
    assert src == "ytdlp"
    assert path == fake_path
