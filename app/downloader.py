"""下载引擎：musicdl 多源封装 + 元数据内嵌。

下载源按配置顺序尝试，每个源独立隔离失败；
下载后统一用 mutagen 重写标签（标题/歌手/专辑/封面/歌词）。
"""

from __future__ import annotations

import importlib
import logging
import re
import shutil
import time
from pathlib import Path

import requests
from mutagen.flac import FLAC, Picture
from mutagen.id3 import APIC, ID3, TALB, TIT2, TPE1, USLT, error as ID3error
from mutagen.mp3 import MP3
from mutagen.mp4 import MP4, MP4Cover

from . import matcher
from .util import RateLimiter

log = logging.getLogger(__name__)

# 短名 -> musicdl 客户端类名
SOURCE_CLIENTS = {
    "netease": "NeteaseMusicClient",
    "kuwo": "KuwoMusicClient",
    "migu": "MiguMusicClient",
    "bodian": "BodianMusicClient",
    "qq": "QQMusicClient",
    "kugou": "KugouMusicClient",
    "qianqian": "QianqianMusicClient",
}

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"

# musicdl 的网易云客户端默认从高音质向低音质遍历，可能拿到 100MB+ 的母带文件。
# 我们限制为 320k(exhigh)/128k(standard) 的 mp3，控制体积。
_MUSICDL_NETEASE_QUALITIES = ["exhigh", "standard"]


def _patch_musicdl():
    """对 musicdl 做运行时校准（模块级补丁）。"""
    candidates = [
        "musicdl.modules.sources.netease",
        "musicdl.sources.netease",
        "musicdl.modules.netease",
    ]
    for name in candidates:
        try:
            mod = importlib.import_module(name)
        except ImportError:
            continue
        if hasattr(mod, "MUSIC_QUALITIES"):
            mod.MUSIC_QUALITIES = list(_MUSICDL_NETEASE_QUALITIES)
            return
    log.warning("无法定位 musicdl 网易云模块以限制音质（不影响下载，仅可能下载大体积母带文件）")


class DownloadError(Exception):
    pass


class MusicDLEngine:
    """musicdl 多源下载引擎。懒加载，单源失败不影响其他源。"""

    def __init__(self, sources: list[str], work_dir: Path, netease_cookie: str = "",
                 title_threshold: int = 85, max_duration_diff: int = 12, interval: float = 2.0):
        self.sources = [s for s in sources if s in SOURCE_CLIENTS]
        self.work_dir = Path(work_dir)
        self.work_dir.mkdir(parents=True, exist_ok=True)
        self.netease_cookie = netease_cookie
        self.title_threshold = title_threshold
        self.max_duration_diff = max_duration_diff
        self.limiter = RateLimiter(interval)
        self._clients = {}

    def update_config(self, sources: list[str] | None = None, title_threshold: int | None = None,
                      max_duration_diff: int | None = None, interval: float | None = None):
        """热更新下载参数，并重置已缓存的客户端（下次下载时按新配置重建）。"""
        if sources is not None:
            self.sources = [s for s in sources if s in SOURCE_CLIENTS]
        if title_threshold is not None:
            self.title_threshold = title_threshold
        if max_duration_diff is not None:
            self.max_duration_diff = max_duration_diff
        if interval is not None:
            self.limiter = RateLimiter(interval)
        if self._clients:
            log.info("下载参数已热更新，重置 %d 个已缓存的 musicdl 客户端", len(self._clients))
            self._clients.clear()

    def set_netease_cookie(self, cookie: str):
        """热更新网易云 Cookie（扫码登录后调用），旧的网易云客户端作废重建。"""
        self.netease_cookie = cookie
        self._clients.pop("netease", None)

    def cleanup(self, max_age_s: float = 86400):
        """清理 work_dir 中超过 max_age_s 的残留文件，防止磁盘无限增长。"""
        now = time.time()
        removed = 0
        for child in self.work_dir.rglob("*"):
            if not child.is_file():
                continue
            try:
                if now - child.stat().st_mtime > max_age_s:
                    child.unlink()
                    removed += 1
            except OSError:
                pass
        if removed:
            log.info("清理 musicdl 临时残留 %d 个文件", removed)

    def _get_client(self, source: str):
        if source in self._clients:
            return self._clients[source]
        try:
            _patch_musicdl()
            from musicdl import musicdl
        except ImportError as e:
            raise DownloadError(f"musicdl 未安装: {e}")
        client_name = SOURCE_CLIENTS[source]
        cfg = {client_name: {"work_dir": str(self.work_dir / source)}}
        if source == "netease" and self.netease_cookie:
            cfg[client_name]["default_search_cookies"] = self.netease_cookie
            cfg[client_name]["default_download_cookies"] = self.netease_cookie
        try:
            client = musicdl.MusicClient(
                music_sources=[client_name], init_music_clients_cfg=cfg
            )
        except Exception as e:
            log.warning("初始化 musicdl 源 %s 失败: %s", source, e)
            client = None
        self._clients[source] = client
        return client

    @staticmethod
    def _norm_result(info, source: str) -> dict:
        """把 musicdl 的 SongInfo 归一化成 matcher 可用的结构。"""
        get = (lambda k, d="": getattr(info, k, d) or d) if not isinstance(info, dict) \
            else (lambda k, d="": info.get(k, d) or d)
        singers = get("singers") or get("artist")
        if isinstance(singers, str):
            singers = [s.strip() for s in re.split(r"[,、/]", singers) if s.strip()]
        return {
            "name": get("song_name") or get("songname") or get("title") or get("name"),
            "artists": singers or [],
            "album": get("album"),
            "duration": get("duration_s") or get("duration", 0),
            "raw": info,
            "source": source,
        }

    def _download_from_source(self, track, source: str) -> Path | None:
        client = self._get_client(source)
        if client is None:
            return None
        keyword = f"{track.artists[0] if track.artists else ''} {track.title}".strip()
        try:
            results = client.search(keyword=keyword)
        except Exception as e:
            log.warning("musicdl 源 %s 搜索失败: %s", source, e)
            return None
        infos = []
        if isinstance(results, dict):
            for v in results.values():
                infos.extend(v or [])
        elif isinstance(results, list):
            infos = results
        candidates = [self._norm_result(i, source) for i in infos]
        hit = matcher.best_match(track, candidates, self.title_threshold, self.max_duration_diff)
        if not hit:
            log.info("源 %s 无有效匹配: %s", source, keyword)
            return None
        try:
            downloaded = client.download(song_infos=[hit["raw"]])
        except Exception as e:
            log.warning("musicdl 源 %s 下载失败: %s", source, e)
            return None
        if not downloaded:
            log.warning("源 %s 下载无结果", source)
            return None
        save_path = Path(downloaded[0].save_path)
        if not save_path.exists() or save_path.stat().st_size < 100 * 1024:
            log.warning("源 %s 下载文件无效: %s", source, save_path)
            return None
        return save_path

    def download(self, track) -> tuple[Path, str]:
        """按源链尝试下载，返回 (文件路径, 命中的源)。全部失败抛 DownloadError。"""
        for source in self.sources:
            self.limiter.wait()
            log.info("尝试源 %s: %s - %s", source, "/".join(track.artists), track.title)
            path = self._download_from_source(track, source)
            if path:
                return path, source
        raise DownloadError("所有下载源均失败")


# ---------------- 元数据内嵌 ----------------

def _fetch_cover(url: str) -> bytes | None:
    if not url:
        return None
    try:
        resp = requests.get(url, headers={"User-Agent": UA}, timeout=20)
        resp.raise_for_status()
        if len(resp.content) > 1024:
            return resp.content
    except Exception as e:
        log.debug("封面下载失败: %s", e)
    return None


def embed_metadata(path: Path, track, cover_url: str = "", lyrics: str | None = None):
    """按格式内嵌标题/歌手/专辑/封面/歌词。失败仅记录，不阻断流程。"""
    ext = path.suffix.lower()
    artists_str = "/".join(track.artists)
    cover = _fetch_cover(cover_url)
    try:
        if ext == ".mp3":
            _tag_mp3(path, track, artists_str, cover, lyrics)
        elif ext == ".flac":
            _tag_flac(path, track, artists_str, cover, lyrics)
        elif ext in (".m4a", ".mp4", ".aac"):
            _tag_m4a(path, track, artists_str, cover, lyrics)
        else:
            log.info("暂不支持内嵌标签的格式: %s", ext)
    except Exception as e:
        log.warning("写入标签失败 %s: %s", path.name, e)


def _tag_mp3(path, track, artists_str, cover, lyrics):
    try:
        audio = ID3(path)
    except ID3error:
        audio = ID3()
    audio["TIT2"] = TIT2(encoding=3, text=track.title)
    audio["TPE1"] = TPE1(encoding=3, text=artists_str)
    audio["TALB"] = TALB(encoding=3, text=track.album or "")
    audio.delall("APIC")
    if cover:
        audio.add(APIC(encoding=3, mime="image/jpeg", type=3, desc="Cover", data=cover))
    if lyrics:
        audio["USLT::'und'"] = USLT(encoding=3, lang="und", desc="lyrics", text=lyrics)
    audio.save(path)


def _tag_flac(path, track, artists_str, cover, lyrics):
    audio = FLAC(path)
    audio["title"] = track.title
    audio["artist"] = artists_str
    audio["album"] = track.album or ""
    if lyrics:
        audio["lyrics"] = lyrics
    if cover:
        audio.clear_pictures()
        pic = Picture()
        pic.type = 3
        pic.mime = "image/jpeg"
        pic.desc = "Cover"
        pic.data = cover
        audio.add_picture(pic)
    audio.save()


def _tag_m4a(path, track, artists_str, cover, lyrics):
    audio = MP4(path)
    audio["\xa9nam"] = [track.title]
    audio["\xa9ART"] = [artists_str]
    audio["\xa9alb"] = [track.album or ""]
    if lyrics:
        audio["\xa9lyr"] = [lyrics]
    if cover:
        audio["covr"] = [MP4Cover(cover, imageformat=MP4Cover.FORMAT_JPEG)]
    audio.save()


def sniff_duration_ms(path: Path) -> int:
    """读取音频真实时长（毫秒），失败返回 0。"""
    try:
        ext = path.suffix.lower()
        if ext == ".mp3":
            return int(MP3(path).info.length * 1000)
        if ext == ".flac":
            return int(FLAC(path).info.length * 1000)
        if ext in (".m4a", ".mp4", ".aac"):
            return int(MP4(path).info.length * 1000)
    except Exception:
        pass
    return 0


def move_file(src: Path, dst: Path) -> Path:
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        src.unlink(missing_ok=True)
        return dst
    shutil.move(str(src), str(dst))
    return dst


def cleanup_dir(path: Path):
    shutil.rmtree(path, ignore_errors=True)
