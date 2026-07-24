"""每日任务编排：推荐聚合 -> 去重 -> 匹配 -> 下载 -> 入库 -> 歌单文件。"""

import json
import logging
import os
import threading
import time
from pathlib import Path

from . import matcher
from .db import DB
from .downloader import (DownloadError, MusicDLEngine, embed_metadata,
                         move_file, sniff_duration_ms)
from .library import SubsonicClient, display_name, write_lrc_sidecar, write_m3u8
from .api_client import NCMAPIClient
from .sources.base import Track
from .sources.lastfm import LastFmSource
from .sources.listenbrainz import ListenBrainzSource
from .sources.netease_daily import NeteaseDailySource
from .sources.netease_playlist import NeteasePlaylistSource
from .util import RateLimiter, safe_name, track_key

log = logging.getLogger(__name__)

DISCOVER_DIR = "Discover"


class Jobs:
    def __init__(self, cfg, db: DB):
        self.cfg = cfg
        self.db = db
        self.ncm = NCMAPIClient(cfg.ncm_api_url)
        if cfg.netease_cookie:
            self.ncm.set_cookie(cfg.netease_cookie)
        self.engine = MusicDLEngine(
            cfg.dl_sources, cfg.data_dir / "tmp_dl",
            netease_cookie=cfg.netease_cookie,
            title_threshold=cfg.title_threshold,
            max_duration_diff=cfg.max_duration_diff,
            interval=cfg.dl_interval,
        )
        self.subsonic = (
            SubsonicClient(cfg.navidrome.url, cfg.navidrome.username, cfg.navidrome.password)
            if cfg.navidrome.enabled else None
        )
        self.ncm_limiter = RateLimiter(0.5)
        self._lock = threading.Lock()
        self.last_cookie_ok: bool | None = None
        self._abort = threading.Event()
        self.aborted = False

    def stop(self):
        """请求中止正在运行的每日任务（下一首曲目前停止）。"""
        self._abort.set()

    def set_cookie(self, cookie: str):
        """热更新网易云 Cookie 并持久化到 cookie 文件。"""
        self.ncm.set_cookie(cookie)
        try:
            (self.cfg.data_dir / "cookie.txt").write_text(cookie, encoding="utf-8")
        except Exception as e:
            log.warning("写入 cookie 文件失败: %s", e)
        try:
            self.last_cookie_ok = self.ncm.check_cookie()
        except Exception as e:
            log.warning("Cookie 验证失败: %s", e)
            self.last_cookie_ok = False

    # ---------- 推荐源 ----------

    def _build_sources(self):
        srcs = []
        sc = self.cfg.sources
        if sc.get("netease_daily") and sc["netease_daily"].enabled:
            srcs.append(NeteaseDailySource(self.ncm))
        if sc.get("netease_playlists") and sc["netease_playlists"].enabled:
            playlists = sc["netease_playlists"].extra.get("playlists") or []
            if playlists:
                srcs.append(NeteasePlaylistSource(self.ncm, playlists))
        if sc.get("listenbrainz") and sc["listenbrainz"].enabled:
            username = sc["listenbrainz"].extra.get("username", "")
            if username:
                srcs.append(ListenBrainzSource(username))
        if sc.get("lastfm") and sc["lastfm"].enabled:
            extra = sc["lastfm"].extra
            if extra.get("api_key") and extra.get("username"):
                srcs.append(LastFmSource(extra["api_key"], extra["username"]))
        return srcs

    # ---------- 单曲处理 ----------

    def _resolve_ncm(self, track: Track) -> bool:
        """为没有 ncm_id 的曲目搜索网易云并回填元数据。成功返回 True。"""
        if track.ncm_id:
            return True
        self.ncm_limiter.wait()
        keyword = f"{track.artists[0] if track.artists else ''} {track.title}".strip()
        candidates = self.ncm.search(keyword, limit=10)
        hit = matcher.best_match(
            track, candidates, self.cfg.title_threshold, self.cfg.max_duration_diff
        )
        if not hit:
            return False
        track.ncm_id = hit["id"]
        # 用网易云元数据校准（更标准）
        track.title = hit["name"]
        track.artists = hit["artists"]
        track.album = hit["album"] or track.album
        track.duration_ms = track.duration_ms or hit["duration_ms"]
        track.raw["pic_url"] = hit.get("pic_url", "")
        return True

    def _process_one(self, track: Track, position: int = 0) -> str:
        """处理一首曲目，返回结果: downloaded/existed/skipped/failed。"""
        key = track_key(track.artists, track.title)
        playlist = track.playlist
        self.db.upsert_track(key, track.title, track.artists, track.album,
                             origin=track.origin, ncm_id=track.ncm_id, playlist=playlist)

        row = self.db.get_track(key)
        if row and row["status"] in ("downloaded", "existed"):
            self.db.add_playlist_item(playlist, key, position)
            return "skipped"

        # 曲库查重（Subsonic）
        if self.subsonic:
            try:
                if self.subsonic.exists(track, self.cfg.title_threshold, self.cfg.max_duration_diff):
                    self.db.mark_existed(key)
                    self.db.add_playlist_item(playlist, key, position)
                    return "existed"
            except Exception as e:
                log.warning("查重失败（继续下载）: %s", e)

        # 匹配网易云（拿元数据/歌词/免费音源）
        try:
            self._resolve_ncm(track)
            if track.ncm_id and row and not row["ncm_id"]:
                self.db.set_ncm_id(key, track.ncm_id)
        except Exception as e:
            log.warning("网易云解析失败: %s", e)

        lyrics_text, cover_url = None, track.raw.get("pic_url", "")
        if track.ncm_id:
            try:
                self.ncm_limiter.wait()
                detail = self.ncm.song_detail([track.ncm_id])
                if detail:
                    cover_url = detail[0].get("pic_url") or cover_url
                olrc, tlrc = self.ncm.lyric(track.ncm_id)
                lyrics_text = _merge_lrc(olrc, tlrc)
            except Exception as e:
                log.debug("网易云元数据获取失败(%s): %s", track.ncm_id, e)

        # 下载：走 musicdl 多源链
        audio_path, dl_source = None, ""
        tmp_dir = self.cfg.data_dir / "tmp_one"
        tmp_dir.mkdir(parents=True, exist_ok=True)
        if audio_path is None:
            try:
                audio_path, dl_source = self.engine.download(track)
            except DownloadError as e:
                log.warning("下载失败 %s - %s: %s", "/".join(track.artists), track.title, e)
            except Exception as e:
                log.exception("下载异常: %s", e)

        if audio_path is None:
            self.db.mark_failed(key, "download_failed" if track.ncm_id else "match_failed")
            return "failed"

        # 时长校验（仅警告）
        real_ms = sniff_duration_ms(audio_path)
        if track.duration_ms and real_ms and abs(real_ms - track.duration_ms) > 20 * 1000:
            log.warning("时长偏差较大(%ds vs %ds): %s", real_ms // 1000,
                        track.duration_ms // 1000, track.title)

        # 入库：内嵌标签 + 移动 + 歌词
        subdir = (Path("NetEase") / safe_name(playlist)) if track.origin.startswith("playlist:") else Path(DISCOVER_DIR)
        filename = f"{display_name(track)}{audio_path.suffix.lower()}"
        dest = self.cfg.music_dir / subdir / filename
        embed_metadata(audio_path, track, cover_url, lyrics_text)
        try:
            move_file(audio_path, dest)
        except Exception as e:
            log.error("移动文件失败: %s", e)
            self.db.mark_failed(key, "io_error")
            return "failed"
        write_lrc_sidecar(dest, lyrics_text)

        rel_path = str(subdir / filename)
        self.db.mark_downloaded(key, rel_path, dl_source)
        self.db.add_playlist_item(playlist, key, position)
        log.info("[OK][%s] %s", dl_source, filename)
        return "downloaded"

    # ---------- 歌单文件 ----------

    def _regen_playlist_files(self, playlists: list[str]):
        """重建歌单文件：m3u8 与音频文件同目录，条目用相对路径。"""
        for playlist in playlists:
            if not playlist:
                continue
            rows = self.db.tracks_for_playlist(playlist)
            if not rows:
                continue
            # 以第一个文件所在目录为歌单文件位置（同一歌单的文件按构造都在同一目录）
            first_rel = Path(rows[0]["file_path"])
            target_dir = self.cfg.music_dir / first_rel.parent
            items = []
            for r in rows:
                artists = json.loads(r["artists"]) if isinstance(r["artists"], str) else r["artists"]
                rel = os.path.relpath(self.cfg.music_dir / r["file_path"], target_dir)
                items.append(({"title": r["title"], "artists": artists}, rel))
            try:
                write_m3u8(target_dir, playlist, items)
            except Exception as e:
                log.error("生成歌单文件失败 %s: %s", playlist, e)

    # ---------- 主流程 ----------

    def daily_run(self):
        if not self._lock.acquire(blocking=False):
            log.warning("已有任务在运行，跳过本次")
            return None
        run_id = self.db.run_start()
        stats = {"sources": {}, "downloaded": 0, "existed": 0, "skipped": 0,
                 "failed": 0, "retried": 0, "cookie_ok": None}
        started = time.time()
        try:
            log.info("========== 每日同步开始 ==========")
            self._abort.clear()
            self.aborted = False
            self.last_cookie_ok = self.ncm.check_cookie()
            stats["cookie_ok"] = self.last_cookie_ok
            if not self.last_cookie_ok:
                log.warning("网易云 Cookie 无效或未配置：日推/完整歌单不可用，搜索与免费音源仍可用")

            affected_playlists = set()

            # 1. 重试队列
            due = self.db.due_retries()
            if due:
                log.info("处理重试队列: %d 首", len(due))
            for row in due:
                if self._abort.is_set():
                    self.aborted = True
                    log.warning("收到中止信号，停止重试队列处理")
                    break
                track = Track(title=row["title"], artists=json.loads(row["artists"]),
                              album=row["album"], ncm_id=row["ncm_id"],
                              origin=row["origin"], playlist=row["playlist"])
                result = self._process_one(track)
                stats["retried"] += 1
                stats[result] = stats.get(result, 0) + 1
                if result in ("downloaded", "existed"):
                    affected_playlists.add(row["playlist"])

            # 2. 拉取各推荐源
            all_tracks: list[Track] = []
            for source in self._build_sources():
                if source.name.startswith("netease") and not self.last_cookie_ok:
                    log.warning("跳过源 %s（Cookie 无效）", source.name)
                    stats["sources"][source.name] = "skipped(cookie)"
                    continue
                try:
                    tracks = source.fetch()
                    stats["sources"][source.name] = len(tracks)
                    all_tracks.extend(tracks)
                except Exception as e:
                    log.error("推荐源 %s 失败: %s", source.name, e)
                    stats["sources"][source.name] = f"error: {e}"

            # 3. 分类：歌单同步 与 推荐聚合
            sync_tracks = [t for t in all_tracks if t.origin.startswith("playlist:")]
            discover_tracks = [t for t in all_tracks if not t.origin.startswith("playlist:")]

            # 歌单同步：位置即歌单内顺序，只处理新歌（playlist_items 里已有的跳过）
            for t in sync_tracks:
                self.db.upsert_track(track_key(t.artists, t.title), t.title, t.artists,
                                     t.album, origin=t.origin, ncm_id=t.ncm_id, playlist=t.playlist)
            pending_sync = []
            positions = {}
            for i, t in enumerate(sync_tracks):
                k = track_key(t.artists, t.title)
                positions[(t.playlist, k)] = i
                if k not in self.db.playlist_keys(t.playlist):
                    pending_sync.append(t)
            log.info("歌单同步: 共 %d 首，新增待处理 %d 首", len(sync_tracks), len(pending_sync))

            # 推荐聚合：按 key 去重合并（取最高分，合并来源）
            merged = {}
            for t in discover_tracks:
                k = track_key(t.artists, t.title)
                if k in merged:
                    old = merged[k]
                    old.score = max(old.score, t.score) + 0.1
                    old.origin = f"{old.origin},{t.origin}" if t.origin not in old.origin else old.origin
                    old.ncm_id = old.ncm_id or t.ncm_id
                else:
                    merged[k] = t
            discover_sorted = sorted(merged.values(), key=lambda t: -t.score)
            capped = discover_sorted[: self.cfg.discover_daily_limit]
            log.info("推荐聚合: %d 首（去重后 %d，本次处理 %d）",
                     len(discover_tracks), len(merged), len(capped))

            # 4. 下载处理
            for t in pending_sync + capped:
                if self._abort.is_set():
                    self.aborted = True
                    log.warning("收到中止信号，停止下载处理")
                    break
                result = self._process_one(t, positions.get((t.playlist, track_key(t.artists, t.title)), 0))
                stats[result] = stats.get(result, 0) + 1
                if result in ("downloaded", "existed", "skipped"):
                    affected_playlists.add(t.playlist)

            # 5. 重建受影响的歌单文件
            self._regen_playlist_files(list(affected_playlists))

            stats["duration_s"] = round(time.time() - started, 1)
            log.info("========== 每日同步完成: %s ==========", stats)
            return stats
        except Exception as e:
            log.exception("每日任务异常: %s", e)
            stats["error"] = str(e)
            return stats
        finally:
            self.db.run_finish(run_id, stats)
            self._lock.release()


def _merge_lrc(olrc: str | None, tlrc: str | None) -> str | None:
    """合并原文与翻译歌词（同时间轴原文在上、翻译在下）。"""
    if not olrc:
        return None
    if not tlrc:
        return olrc
    import re
    pattern = re.compile(r"^\[(\d{1,2}:\d{2}(?:[.:]\d{1,3})?)\](.*)$")
    trans = {}
    for line in tlrc.splitlines():
        m = pattern.match(line.strip())
        if m and m.group(2).strip():
            trans.setdefault(m.group(1), []).append(m.group(2).strip())
    out = []
    for line in olrc.splitlines():
        out.append(line)
        m = pattern.match(line.strip())
        if m and m.group(1) in trans:
            for t in trans[m.group(1)]:
                out.append(f"[{m.group(1)}]{t}")
    return "\n".join(out)
