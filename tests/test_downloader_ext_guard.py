"""下载产物格式白名单守卫测试。

背景：酷我"臻品音质"等私有加密格式（.mflac 等）会被 Navidrome 的扩展名
白名单拒收（IsAudioFile 只认 audio/* MIME），导致歌单出现幽灵条目。
下载端必须在落盘入库前拒收这类格式并落下一源。
"""

from pathlib import Path
from types import SimpleNamespace

from app.downloader import (
    LIBRARY_AUDIO_EXTENSIONS,
    DownloadError,
    MusicDLEngine,
    YTDLP_SOURCE,
)


class _FakeSongInfo:
    """musicdl SongInfo 的最小替身，供 _norm_result 提取字段。"""

    def __init__(self, name="JANE DOE", artists="米津玄師",
                 album="LOSER", duration_s=211, save_path=""):
        self.song_name = name
        self.singers = artists
        self.album = album
        self.duration_s = duration_s
        self.save_path = save_path


class _FakeClient:
    def __init__(self, save_path):
        self._save_path = save_path

    def search(self, keyword):
        return [_FakeSongInfo(save_path=self._save_path)]

    def download(self, song_infos):
        return [SimpleNamespace(save_path=self._save_path)]


def _make_track():
    return SimpleNamespace(title="JANE DOE", artists=["米津玄師"],
                           album="LOSER", duration_ms=211_000, origin="discover")


def _seed_file(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\x00" * 1024 * 1024)  # >100KB，通过大小校验
    return path


def test_library_extensions_exclude_encrypted_formats():
    assert ".mp3" in LIBRARY_AUDIO_EXTENSIONS
    assert ".flac" in LIBRARY_AUDIO_EXTENSIONS
    for bad in (".mflac", ".kwm", ".mgg", ".ncm", ".mp3.enc"):
        assert bad not in LIBRARY_AUDIO_EXTENSIONS


def test_musicdl_source_rejects_encrypted_extension(tmp_path, monkeypatch):
    engine = MusicDLEngine(["kuwo"], tmp_path / "work", interval=0)
    mflac = _seed_file(tmp_path / "work" / "kuwo" / "JANE DOE.mflac")
    engine._clients["kuwo"] = _FakeClient(str(mflac))

    # matcher 走真实逻辑（标题/歌手完全一致可命中），仅验证格式守卫
    result = engine._download_from_source(_make_track(), "kuwo")

    assert result is None
    assert not mflac.exists(), "加密文件应被删除，不残留工作区"


def test_musicdl_source_accepts_whitelisted_extension(tmp_path):
    engine = MusicDLEngine(["netease"], tmp_path / "work", interval=0)
    flac = _seed_file(tmp_path / "work" / "netease" / "JANE DOE.flac")
    engine._clients["netease"] = _FakeClient(str(flac))

    result = engine._download_from_source(_make_track(), "netease")

    assert result == flac
    assert flac.exists()


def test_download_falls_through_to_next_source(tmp_path, monkeypatch):
    """前序源返回 .mflac 被拒后，应落到下一源并成功下载 .flac。"""
    engine = MusicDLEngine(["kuwo", "netease"], tmp_path / "work", interval=0)
    mflac = _seed_file(tmp_path / "work" / "kuwo" / "JANE DOE.mflac")
    flac = _seed_file(tmp_path / "work" / "netease" / "JANE DOE.flac")
    engine._clients["kuwo"] = _FakeClient(str(mflac))
    engine._clients["netease"] = _FakeClient(str(flac))

    path, source = engine.download(_make_track())

    assert source == "netease"
    assert path == flac
    assert not mflac.exists()


def test_ytdlp_rejects_encrypted_artifact(tmp_path, monkeypatch):
    """yt-dlp 路径同样受白名单守卫（防御性：探测与下载间格式可能偏差）。"""
    engine = MusicDLEngine([YTDLP_SOURCE], tmp_path / "work", interval=0)
    mflac = _seed_file(tmp_path / "work" / YTDLP_SOURCE / "dQw4w9WgXcQ.mflac")

    monkeypatch.setattr(
        engine, "_ytdlp_search", lambda query, use_cookies=True: [
            {"id": "dQw4w9WgXcQ", "title": "米津玄師 - JANE DOE", "duration": 211.0},
        ],
    )
    monkeypatch.setattr(engine, "_pick_ytdlp_candidate", lambda track, entries: entries[0])

    def fake_probe(vid, use_cookies):
        return {"use_cookies": use_cookies, "error": "",
                "format": {"format_id": "140", "ext": "m4a", "abr": 128.0}}

    monkeypatch.setattr(engine, "_probe_ytdlp_formats", fake_probe)
    monkeypatch.setattr(
        engine, "_run_ytdlp",
        lambda args, timeout=240, suppress_warnings=True, use_cookies=True:
        SimpleNamespace(returncode=0, stdout="", stderr=""),
    )

    assert engine._download_ytdlp(_make_track()) is None
    assert not mflac.exists()
