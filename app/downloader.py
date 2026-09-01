"""下载引擎：musicdl 多源封装 + 元数据内嵌。

下载源按配置顺序尝试，每个源独立隔离失败；
下载后统一用 mutagen 重写标签（标题/歌手/专辑/封面/歌词）。
"""

from __future__ import annotations

import importlib
import json
import logging
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

import requests
from rapidfuzz import fuzz as _rapidfuzz
from mutagen.flac import FLAC, Picture
from mutagen.id3 import APIC, ID3, TALB, TIT2, TPE1, USLT, error as ID3error
from mutagen.mp3 import MP3
from mutagen.mp4 import MP4, MP4Cover

from . import matcher
from .util import RateLimiter, normalize

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

# yt-dlp 兜底源（非 musicdl 客户端，走 subprocess 调用）
YTDLP_SOURCE = "ytdlp"

VALID_SOURCES = set(SOURCE_CLIENTS) | {YTDLP_SOURCE}

# 可入库音频格式白名单（Navidrome 能识别、本流程可正常消费）。
# 源方私有/加密格式（酷我/QQ 的 .mflac、.kwm、.mgg、.ncm 等）一律拒收：
# 既无法通过 Navidrome 的扩展名白名单入库，任何播放器也无法直接播放。
LIBRARY_AUDIO_EXTENSIONS = {".mp3", ".flac", ".m4a", ".mp4", ".aac", ".ogg", ".opus", ".wav"}

# yt-dlp 搜索候选数 / 单曲下载超时
_YTDLP_SEARCH_COUNT = 5
_YTDLP_TIMEOUT = 240

# yt-dlp 403（YouTube IP 风控）处理：
# 单曲 403 立即降级下一源；连续多曲 403 触发熔断，冷却期内跳过 ytdlp 源，避免整场任务反复撞风控
_YTDLP_403_STREAK_LIMIT = 5
_YTDLP_403_COOLDOWN = 3600
_YTDLP_COOKIE_PROBE_URL = "https://www.youtube.com/feed/history"

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"

# musicdl 的网易云客户端默认从高音质向低音质遍历，可能拿到 100MB+ 的母带文件。
# 我们限制为 320k(exhigh)/128k(standard) 的 mp3，控制体积。
_MUSICDL_NETEASE_QUALITIES = ["exhigh", "standard"]

# YouTube 候选标题含这些关键词即判为"非原曲"版本（BGM/纯音乐/伴奏等），跳过。
# 这类视频基础标题匹配分照样很高，不过滤就会把纯 BGM 当成原曲下下来。
# 注意：不含"纯享"——那是网易云音质标签（无损纯享=高音质版），不是 BGM。
_BGM_KEYWORDS = (
    "bgm", "纯音乐", "instrumental", "伴奏", "karaoke", "背景音乐",
)

# 下载后时长校验阈值：
# - 比期望短 _DUR_TRUNCATE_RATIO 以上 → 判截断/预览片段，拒收
# - 比期望长 _DUR_TOO_LONG_RATIO 以上 → 判错误视频（现场版/BGM 循环等），拒收
# - 期望时长未知时，低于 _DUR_FLOOR_MS 的兜底拒收（绝大多数歌曲 > 40s）
_DUR_TRUNCATE_RATIO = 0.8
_DUR_TOO_LONG_RATIO = 1.5
_DUR_FLOOR_MS = 40 * 1000


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
                 title_threshold: int = 85, max_duration_diff: int = 12, interval: float = 2.0,
                 ytdlp_cookies: Path | None = None):
        self.sources = [s for s in sources if s in VALID_SOURCES]
        self.work_dir = Path(work_dir)
        self.work_dir.mkdir(parents=True, exist_ok=True)
        self.netease_cookie = netease_cookie
        self.ytdlp_cookies = ytdlp_cookies
        self.title_threshold = title_threshold
        self.max_duration_diff = max_duration_diff
        self.limiter = RateLimiter(interval)
        self._clients = {}
        self._ytdlp_403_streak = 0
        self._ytdlp_disabled_until = 0.0

    def update_config(self, sources: list[str] | None = None, title_threshold: int | None = None,
                      max_duration_diff: int | None = None, interval: float | None = None,
                      ytdlp_cookies: Path | None = None):
        """热更新下载参数，并重置已缓存的客户端（下次下载时按新配置重建）。"""
        if sources is not None:
            self.sources = [s for s in sources if s in VALID_SOURCES]
        if title_threshold is not None:
            self.title_threshold = title_threshold
        if max_duration_diff is not None:
            self.max_duration_diff = max_duration_diff
        if interval is not None:
            self.limiter = RateLimiter(interval)
        if ytdlp_cookies is not None:
            self.ytdlp_cookies = Path(ytdlp_cookies)
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
        if source == YTDLP_SOURCE:
            return self._download_ytdlp(track)
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
        # 过滤 BGM/纯音乐/伴奏等非原曲版本，避免把纯 BGM 当原曲下下来
        candidates = [c for c in candidates
                      if not any(kw in (c.get("name") or "").lower() for kw in _BGM_KEYWORDS)]
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
        if save_path.suffix.lower() not in LIBRARY_AUDIO_EXTENSIONS:
            # 酷我"臻品音质"等私有加密格式（.mflac 等）：拒收并落下一源，
            # 避免加密文件入库后 Navidrome 扫不到、歌单出现幽灵条目。
            log.warning("源 %s 返回非入库格式 %s（私有/加密音频），跳过: %s",
                        source, save_path.suffix, save_path.name)
            save_path.unlink(missing_ok=True)
            return None
        return save_path

    def download(self, track) -> tuple[Path, str]:
        """按源链尝试下载，返回 (文件路径, 命中的源)。全部失败抛 DownloadError。

        每个源的产物都过一遍时长校验：截断/预览片段、明显错误视频会被拒收，
        删除产物后落下一源，避免坏文件入库。
        """
        for source in self.sources:
            self.limiter.wait()
            log.info("尝试源 %s: %s - %s", source, "/".join(track.artists), track.title)
            path = self._download_from_source(track, source)
            if not path:
                continue
            if not self._validate_duration(path, track):
                log.warning("源 %s 产物未通过时长校验，弃用并落下一源: %s", source, path.name)
                path.unlink(missing_ok=True)
                continue
            return path, source
        raise DownloadError("所有下载源均失败")

    # ---------- yt-dlp 兜底源 ----------

    def _note_ytdlp_403(self):
        """记录一次 403；连续达到阈值则熔断 ytdlp 源一段时间。"""
        self._ytdlp_403_streak += 1
        if self._ytdlp_403_streak >= _YTDLP_403_STREAK_LIMIT and time.time() >= self._ytdlp_disabled_until:
            self._ytdlp_disabled_until = time.time() + _YTDLP_403_COOLDOWN
            log.warning("yt-dlp 连续 %d 次 403（疑似出口 IP 被 YouTube 风控），%d 秒内跳过 ytdlp 源",
                        self._ytdlp_403_streak, _YTDLP_403_COOLDOWN)

    def _reset_ytdlp_403(self):
        if self._ytdlp_403_streak:
            log.info("yt-dlp 恢复正常，清零 403 连续计数（%d）", self._ytdlp_403_streak)
            self._ytdlp_403_streak = 0

    def _run_ytdlp(self, args: list[str], timeout: int = _YTDLP_TIMEOUT,
                   suppress_warnings: bool = True, use_cookies: bool = True) -> subprocess.CompletedProcess:
        """以模块方式调用 yt-dlp（不依赖 PATH 上的可执行文件）。

        配置了 YouTube Cookie 且文件存在时自动附加 --cookies（登录态可显著降低 403 风控）。
        """
        if use_cookies and self.ytdlp_cookies and self.ytdlp_cookies.exists():
            args = ["--cookies", str(self.ytdlp_cookies), *args]
        command = [sys.executable, "-m", "yt_dlp"]
        if suppress_warnings:
            command.append("--no-warnings")
        command.append("--no-update")
        # yt-dlp 2026.08+ 需要 EJS 远程挑战求解器，否则签名校验失败、格式列表残缺
        command += ["--remote-components", "ejs:github"]
        return subprocess.run(
            [*command, *args],
            capture_output=True, text=True, timeout=timeout,
        )

    def check_ytdlp_cookie(self, timeout: int = 60) -> dict:
        """验证 YouTube Cookie，返回 valid/invalid/unknown 三态结果。

        普通公开视频不要求登录，不能用来证明 Cookie 有效；这里探测需要登录的
        YouTube 历史记录页。网络风控、403、PO Token 等情况统一返回 unknown，
        避免把暂时的下载问题误判成 Cookie 失效。
        """
        path = self.ytdlp_cookies
        if not path:
            return {"state": "missing", "ok": False, "message": "未配置 YouTube Cookie 文件"}
        if not path.exists():
            return {"state": "missing", "ok": False,
                    "message": f"Cookie 文件不存在: {path}"}
        try:
            head = path.read_text(encoding="utf-8", errors="replace")[:4096]
        except OSError as e:
            return {"state": "unknown", "ok": None, "message": f"无法读取 Cookie 文件: {e}"}
        if not (head.startswith("# Netscape HTTP Cookie File")
                or head.startswith("# HTTP Cookie File")):
            return {"state": "invalid", "ok": False,
                    "message": "Cookie 文件不是 Netscape/Mozilla 格式"}

        try:
            proc = self._run_ytdlp([
                "--flat-playlist", "--playlist-end", "1", "--skip-download", "-J",
                _YTDLP_COOKIE_PROBE_URL,
            ], timeout=timeout, suppress_warnings=False)
        except subprocess.TimeoutExpired:
            return {"state": "unknown", "ok": None, "message": "YouTube Cookie 探测超时"}
        except Exception as e:
            return {"state": "unknown", "ok": None, "message": f"探测异常: {type(e).__name__}"}

        text = f"{proc.stdout or ''}\n{proc.stderr or ''}".lower()
        if ("cookies are no longer valid" in text
                or "login_required" in text
                or "sign in to confirm" in text
                or "sign in to view" in text):
            return {"state": "invalid", "ok": False,
                    "message": "YouTube Cookie 已失效或登录态不足"}
        if proc.returncode == 0:
            return {"state": "valid", "ok": True, "message": "YouTube Cookie 探测成功"}

        if "page needs to be reloaded" in text:
            return {"state": "unknown", "ok": None,
                    "message": "YouTube 要求重新加载，暂时无法确认 Cookie"}
        if "403" in text or "429" in text or "bot" in text or "po token" in text:
            return {"state": "unknown", "ok": None,
                    "message": "YouTube 返回风控/验证错误，暂时无法确认 Cookie"}
        return {"state": "unknown", "ok": None,
                "message": "YouTube Cookie 探测失败，原因不明确"}

    def _ytdlp_search(self, query: str, use_cookies: bool = True) -> list[dict]:
        """YouTube 搜索候选，返回 [{id, title, duration(秒)}]。"""
        proc = self._run_ytdlp(
            ["-J", "--flat-playlist", "--skip-download", f"ytsearch{_YTDLP_SEARCH_COUNT}:{query}"],
            timeout=60, use_cookies=use_cookies,
        )
        if proc.returncode != 0:
            err = (proc.stderr or "").strip()[:200]
            log.warning("yt-dlp 搜索失败: %s", err)
            if "403" in err:
                self._note_ytdlp_403()
            return []
        try:
            data = json.loads(proc.stdout)
        except ValueError:
            return []
        out = []
        for e in (data.get("entries") or []):
            if not isinstance(e, dict) or not e.get("id"):
                continue
            dur = e.get("duration") or 0
            try:
                dur = float(dur)
            except (TypeError, ValueError):
                dur = 0
            out.append({"id": str(e["id"]), "title": str(e.get("title") or ""), "duration": dur})
        return out

    def _pick_ytdlp_candidate(self, track, entries: list[dict]) -> dict | None:
        """从 YouTube 候选中挑出匹配曲目：标题分 + 歌手 + 时长三重校验。"""
        best = []
        for e in entries:
            title = (e.get("title") or "").strip()
            if not title:
                continue
            # 过滤 BGM/纯音乐/伴奏等非原曲版本（标题含关键词即跳过）
            if any(kw in title.lower() for kw in _BGM_KEYWORDS):
                log.info("yt-dlp 候选含 BGM/非原曲关键词，跳过: %s", title[:60])
                continue
            # 拆 "歌手 - 歌名"；拆不出则整串参与标题匹配
            parts = re.split(r"\s*[-–—]\s*", title, maxsplit=1)
            if len(parts) == 2 and parts[0] and parts[1]:
                cand_artists, cand_title = [parts[0]], parts[1]
                score = matcher.title_score(track.title, cand_title)
            else:
                cand_artists, cand_title = [], title
                # 无分隔符：容忍标题里的额外噪音词（如"无损纯享"），用 token_set_ratio
                score = max(matcher.title_score(track.title, title),
                            _rapidfuzz.token_set_ratio(normalize(track.title), normalize(title)))
            if score < self.title_threshold:
                continue
            if cand_artists and not matcher.artist_match(track.artists, cand_artists):
                continue
            dur = e.get("duration") or 0
            if (track.duration_ms and dur
                    and abs(track.duration_ms - dur * 1000) > self.max_duration_diff * 1000):
                continue
            best.append((score, e))
        if not best:
            return None
        best.sort(key=lambda x: x[0], reverse=True)
        return best[0][1]

    def _validate_duration(self, path: Path, track) -> bool:
        """下载后时长校验：拒收截断/预览片段和明显错误的视频。

        - 期望时长已知：短于 80% 判截断、长于 150% 判错视频，均拒收；
        - 期望时长未知：低于 40s 兜底拒收（绝大多数歌曲 > 40s）；
        - 读不到时长时放行（不阻断，交给后续流程）。
        """
        real_ms = sniff_duration_ms(path)
        if not real_ms:
            return True
        expected = track.duration_ms
        if expected:
            if real_ms < expected * _DUR_TRUNCATE_RATIO:
                log.warning("时长过短(%ds < 期望 %ds 的 80%%)，判截断/预览，拒收: %s",
                            real_ms // 1000, expected // 1000, path.name)
                return False
            if real_ms > expected * _DUR_TOO_LONG_RATIO:
                log.warning("时长过长(%ds > 期望 %ds 的 150%%)，判错误视频，拒收: %s",
                            real_ms // 1000, expected // 1000, path.name)
                return False
        elif real_ms < _DUR_FLOOR_MS:
            log.warning("时长过短(%ds < 40s 下限)，疑似预览/片段，拒收: %s",
                        real_ms // 1000, path.name)
            return False
        return True

    @staticmethod
    def _best_direct_audio_format(info: dict) -> dict | None:
        """从 yt-dlp JSON 中选出可直接入库的音频-only 格式。"""
        candidates = []
        for fmt in (info.get("formats") or []):
            if not isinstance(fmt, dict):
                continue
            ext = str(fmt.get("ext") or "").lower()
            if ext not in ("m4a", "mp4", "aac"):
                continue
            if str(fmt.get("vcodec") or "none").lower() not in ("none", ""):
                continue
            if str(fmt.get("acodec") or "none").lower() in ("none", ""):
                continue
            format_id = str(fmt.get("format_id") or "")
            if not format_id or not fmt.get("url"):
                continue
            protocol = str(fmt.get("protocol") or "").lower()
            if protocol not in ("http", "https", "m3u8", "m3u8_native"):
                continue
            try:
                abr = float(fmt.get("abr") or fmt.get("tbr") or 0)
            except (TypeError, ValueError):
                abr = 0.0
            ext_rank = {"m4a": 3, "mp4": 2, "aac": 1}[ext]
            protocol_rank = 1 if protocol in ("http", "https") else 0
            candidates.append((ext_rank, protocol_rank, abr, fmt))
        if not candidates:
            return None
        _, _, best_abr, best = max(candidates, key=lambda item: item[:3])
        return {
            "format_id": str(best["format_id"]),
            "ext": str(best.get("ext") or "").lower(),
            "abr": best_abr,
        }

    def _probe_ytdlp_formats(self, vid: str, use_cookies: bool) -> dict:
        """探测一个视频在指定 Cookie 模式下的格式列表。"""
        try:
            proc = self._run_ytdlp([
                "-J", "--skip-download", "--no-playlist",
                "--", f"https://www.youtube.com/watch?v={vid}",
            ], timeout=60, suppress_warnings=False, use_cookies=use_cookies)
        except subprocess.TimeoutExpired:
            return {"use_cookies": use_cookies, "format": None, "error": "探测超时"}
        except Exception as e:
            return {"use_cookies": use_cookies, "format": None,
                    "error": f"探测异常: {type(e).__name__}"}
        text = f"{proc.stdout or ''}\n{proc.stderr or ''}"
        if proc.returncode != 0:
            return {"use_cookies": use_cookies, "format": None,
                    "error": text.strip()[:240] or f"退出码 {proc.returncode}"}
        try:
            info = json.loads(proc.stdout)
        except (TypeError, ValueError):
            return {"use_cookies": use_cookies, "format": None, "error": "JSON 解析失败"}
        return {
            "use_cookies": use_cookies,
            "format": self._best_direct_audio_format(info),
            "error": "",
        }

    def _download_ytdlp(self, track) -> Path | None:
        if time.time() < self._ytdlp_disabled_until:
            log.debug("ytdlp 处于 403 熔断冷却期，跳过")
            return None
        query = f"{track.artists[0] if track.artists else ''} {track.title}".strip()
        work = self.work_dir / YTDLP_SOURCE
        work.mkdir(parents=True, exist_ok=True)
        try:
            entries = self._ytdlp_search(query)
            if not entries and self.ytdlp_cookies and self.ytdlp_cookies.exists():
                entries = self._ytdlp_search(query, use_cookies=False)
        except Exception as e:
            log.warning("yt-dlp 不可用（%s）", e)
            return None
        hit = self._pick_ytdlp_candidate(track, entries)
        if not hit:
            log.info("yt-dlp 无有效匹配: %s", query)
            return None
        vid = hit["id"]
        modes = [False]
        if self.ytdlp_cookies and self.ytdlp_cookies.exists():
            modes.append(True)
        variants = []
        cookie_probe_failed = False
        for use_cookies in modes:
            probe = self._probe_ytdlp_formats(vid, use_cookies)
            fmt = probe.get("format")
            if fmt:
                variants.append({**fmt, "use_cookies": use_cookies})
                log.info("yt-dlp 格式探测 %s: mode=%s, format=%s, abr=%.0fk",
                         vid, "cookie" if use_cookies else "anonymous",
                         fmt["format_id"], fmt["abr"])
            else:
                if use_cookies:
                    cookie_probe_failed = True
                log.info("yt-dlp 格式探测 %s: mode=%s, 无可用音频格式%s",
                         vid, "cookie" if use_cookies else "anonymous",
                         f" ({probe['error'][:120]})" if probe.get("error") else "")
        if cookie_probe_failed:
            # Cookie 模式探测不到可用格式通常意味着 Cookie 已失效或账号被风控
            # （被风控账号带 Cookie 访问时返回的格式列表反而更差）。此时匿名
            # 下载大概率 403，与其白烧一次请求、污染 403 熔断计数，不如直接
            # 判定 ytdlp 源本次不可用，交给后续下载源。
            log.warning("yt-dlp Cookie 模式无可用音频格式，跳过匿名回退"
                        "（疑似 Cookie 失效或账号被风控）: %s", query)
            return None
        # m4a > mp4 > aac；同等格式优先 Cookie 模式，以降低匿名 503 的影响。
        variants.sort(key=lambda v: (
            {"m4a": 3, "mp4": 2, "aac": 1}.get(v["ext"], 0),
            v["abr"],
            int(v["use_cookies"]),
        ), reverse=True)
        if not variants:
            log.warning("yt-dlp 无可用音频格式: %s", query)
            return None

        for variant in variants:
            try:
                proc = self._run_ytdlp([
                    "-f", variant["format_id"],
                    "--no-playlist",
                    "-o", str(work / "%(id)s.%(ext)s"),
                    "--", f"https://www.youtube.com/watch?v={vid}",
                ], use_cookies=variant["use_cookies"])
            except subprocess.TimeoutExpired:
                log.warning("yt-dlp 下载超时: %s (mode=%s)",
                            query, "cookie" if variant["use_cookies"] else "anonymous")
                continue
            except Exception as e:
                log.warning("yt-dlp 下载失败 %s: %s", query, e)
                continue
            if proc.returncode != 0:
                err = (proc.stderr or "").strip()[:200]
                log.warning("yt-dlp 下载失败(%s, mode=%s): %s", proc.returncode,
                            "cookie" if variant["use_cookies"] else "anonymous", err)
                if "403" in err:
                    self._note_ytdlp_403()
                continue
            self._reset_ytdlp_403()
            files = [p for p in work.glob(f"{vid}.*") if p.is_file()]
            if not files:
                log.warning("yt-dlp 下载后未找到产物: %s", vid)
                continue
            save_path = max(files, key=lambda p: p.stat().st_size)
            if save_path.stat().st_size < 100 * 1024:
                log.warning("yt-dlp 下载文件无效: %s", save_path)
                continue
            if save_path.suffix.lower() not in LIBRARY_AUDIO_EXTENSIONS:
                log.warning("yt-dlp 产物非入库格式 %s，跳过: %s",
                            save_path.suffix, save_path.name)
                save_path.unlink(missing_ok=True)
                continue
            return save_path
        return None


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
