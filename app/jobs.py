"""每日任务编排：推荐聚合 -> 去重 -> 匹配 -> 下载 -> 入库 -> 歌单文件。"""

from __future__ import annotations

import datetime
import json
import logging
import os
import re
import threading
import time
from pathlib import Path

from . import matcher
from .db import DB, SCROBBLE_PENDING_KEY, SCROBBLE_TS_KEY
from .downloader import (DownloadError, MusicDLEngine, cleanup_dir,
                         embed_metadata, move_file, sniff_duration_ms)
from .library import SubsonicClient, display_name, write_lrc_sidecar, write_m3u8
from .api_client import NCMAPIClient
from .sources.base import Track
from .sources.lastfm import LastFmSource
from .sources.listenbrainz import ListenBrainzSource, get_recent_listens
from .sources.netease_daily import NeteaseDailySource
from .sources.netease_playlist import NeteasePlaylistSource
from .util import RateLimiter, safe_name, track_key

log = logging.getLogger(__name__)

DISCOVER_DIR = "Discover"
# 每日发现歌单：合并 ListenBrainz（每周歌单/CF）与 Last.fm 等推荐源，按分数限额收取
DAILY_DISCOVER_NAME = "每日发现"
_AUTO_PLAYLIST_PATTERNS = (
    re.compile(r"^网易云日推-(\d{4}-\d{2}-\d{2})$"),
    re.compile(r"^每日发现-(\d{4}-\d{2}-\d{2})$"),
    # 旧版独立推荐歌单（合并进"每日发现"之前的命名），保留以清理历史残留
    re.compile(r"^ListenBrainz-CF-(\d{4}-\d{2}-\d{2})$"),
    re.compile(r"^LastFM-推荐-(\d{4}-\d{2}-\d{2})$"),
)


def _automatic_playlist_date(name: str) -> datetime.date | None:
    """返回自动推荐歌单的日期；固定/手动歌单返回 None。"""
    for pattern in _AUTO_PLAYLIST_PATTERNS:
        match = pattern.fullmatch(str(name or ""))
        if not match:
            continue
        try:
            return datetime.date.fromisoformat(match.group(1))
        except ValueError:
            return None
    return None


def _navidrome_auto_playlist_date(name: str) -> datetime.date | None:
    """从 Navidrome 歌单名解析自动歌单日期。

    Navidrome 导入 m3u8 时歌单名可能带扩展名或改动空格，先归一再匹配。
    """
    base = str(name or "").strip()
    for suffix in (".m3u8", ".m3u"):
        if base.lower().endswith(suffix):
            base = base[: -len(suffix)]
    base = "".join(base.split())
    return _automatic_playlist_date(base)


class Jobs:
    def __init__(self, cfg, db: DB):
        self.cfg = cfg
        self.db = db
        self.ncm = NCMAPIClient(cfg.ncm_api_url)
        self.last_cookie_ok: bool | None = None
        self.last_cookie_check_at = 0.0
        self.youtube_cookie_status = {
            "state": "unchecked", "ok": None, "message": "尚未验证", "checked_at": None,
        }
        self.engine = MusicDLEngine(
            cfg.dl_sources, cfg.data_dir / "tmp_dl",
            netease_cookie=cfg.netease_cookie,
            title_threshold=cfg.title_threshold,
            max_duration_diff=cfg.max_duration_diff,
            interval=cfg.dl_interval,
            ytdlp_cookies=cfg.ytdlp_cookies_file,
        )
        # 下载引擎必须先完成初始化，set_cookie() 会同步更新它的 Cookie。
        if cfg.netease_cookie:
            self.set_cookie(cfg.netease_cookie)
        self.subsonic = (
            SubsonicClient(cfg.navidrome.url, cfg.navidrome.username, cfg.navidrome.password)
            if cfg.navidrome.enabled else None
        )
        self.ncm_limiter = RateLimiter(0.5)
        # ListenBrainz 回传会连续调用 cloudsearch + scrobble；单独限速，避免
        # 一次任务触发网易云的频控或让 ncm-api 上游连接雪崩。
        self.scrobble_limiter = RateLimiter(2.0)
        self._lock = threading.Lock()
        self._abort = threading.Event()
        self.aborted = False

    def stop(self):
        """请求中止正在运行的每日任务（下一首曲目前停止）。"""
        self._abort.set()

    def set_cookie(self, cookie: str):
        """热更新网易云 Cookie 并持久化到 cookie 文件。清洗掉 Path/HttpOnly 等属性。"""
        import re
        pairs = re.findall(r'([A-Za-z_][A-Za-z0-9_]*)=([^;]+)', cookie)
        clean = "; ".join(f"{k}={v.strip()}" for k, v in pairs
                          if k not in ('Path', 'Max-Age', 'HttpOnly', 'Expires',
                                       'Domain', 'Secure', 'SameSite', 'Age'))
        if clean:
            cookie = clean
        self.ncm.set_cookie(cookie)
        self.engine.set_netease_cookie(cookie)
        try:
            self.cfg.cookie_file.parent.mkdir(parents=True, exist_ok=True)
            self.cfg.cookie_file.write_text(cookie, encoding="utf-8")
        except Exception as e:
            log.warning("写入 cookie 文件失败: %s", e)
        try:
            self.refresh_cookie_status()
        except Exception as e:
            log.warning("Cookie 验证失败: %s", e)
            self.last_cookie_ok = False

    def refresh_cookie_status(self) -> bool | None:
        """校验 Cookie，并区分明确失效与暂时无法连接 API。"""
        self.last_cookie_ok = self.ncm.check_cookie_state()
        self.last_cookie_check_at = time.time()
        return self.last_cookie_ok

    def apply_engine_config(self):
        """配置编辑器保存后热更新下载引擎参数。"""
        self.engine.update_config(
            sources=self.cfg.dl_sources,
            title_threshold=self.cfg.title_threshold,
            max_duration_diff=self.cfg.max_duration_diff,
            interval=self.cfg.dl_interval,
            ytdlp_cookies=self.cfg.ytdlp_cookies_file,
        )

    def refresh_youtube_cookie_status(self) -> dict:
        """主动验证 YouTube Cookie；结果区分有效、失效和暂时无法判断。"""
        result = self.engine.check_ytdlp_cookie()
        result["checked_at"] = time.time()
        self.youtube_cookie_status = result
        return result

    def reload_navidrome(self):
        """配置编辑器保存后重建 Subsonic 查重客户端。"""
        self.subsonic = (
            SubsonicClient(self.cfg.navidrome.url, self.cfg.navidrome.username,
                           self.cfg.navidrome.password)
            if self.cfg.navidrome.enabled else None
        )

    def _cleanup_tmp(self):
        """清理临时目录残留，防止磁盘无限增长。"""
        try:
            cleanup_dir(self.cfg.data_dir / "tmp_one")
        except Exception as e:
            log.debug("清理 tmp_one 失败: %s", e)
        try:
            self.engine.cleanup()
        except Exception as e:
            log.debug("清理 musicdl work_dir 失败: %s", e)

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

    def _cleanup_old_playlists(self):
        """删除过期的自动推荐歌单（Navidrome + 本地文件 + 数据库关联），保留音频文件。

        Navidrome 侧独立扫描：歌单名符合自动歌单命名且日期过期即删除，
        不依赖本地文件/数据库记录是否存在，孤儿歌单可自愈。
        """
        retention = max(1, int(getattr(self.cfg, "playlist_retention_days", 3)))
        cutoff = datetime.date.today() - datetime.timedelta(days=retention - 1)
        discover_dir = self.cfg.music_dir / DISCOVER_DIR
        candidates: set[str] = set()

        # 数据库记录可能没有对应的 m3u8 文件，文件扫描也可能发现尚未写入数据库的旧文件。
        for name in self.db.playlist_names():
            playlist_date = _automatic_playlist_date(name)
            if playlist_date and playlist_date < cutoff:
                candidates.add(name)
        # Discover/ 顶层的 m3u8 都是自动歌单（含旧版 LB 每周歌单等无法按名识别的），按文件时间清理
        if discover_dir.exists():
            for path in discover_dir.glob("*.m3u8"):
                try:
                    file_date = datetime.date.fromtimestamp(path.stat().st_mtime)
                except OSError:
                    continue
                if file_date < cutoff:
                    candidates.add(path.stem)

        # Navidrome 自动导入的 m3u8 歌单，源文件删除后不会自动消失，需要显式调 API 删掉。
        # 独立扫描（不依赖上面的 candidates）：本地文件/数据库记录先被清掉后
        # （或早期版本未删 Navidrome 歌单留下的孤儿），按歌单名识别过期自动
        # 歌单仍能删掉，下次运行自动收敛。
        navi_deleted = 0
        if self.subsonic:
            wanted = {SubsonicClient._norm(name) for name in candidates}
            for pl in self.subsonic.list_playlists():
                pid = pl.get("id")
                if not pid:
                    continue
                name = pl.get("name", "")
                expired = SubsonicClient._norm(name) in wanted
                if not expired:
                    d = _navidrome_auto_playlist_date(name)
                    expired = bool(d and d < cutoff)
                if expired and self.subsonic.delete_playlist(pid):
                    navi_deleted += 1

        removed_files = 0
        for playlist in sorted(candidates):
            self.db.delete_playlist(playlist)
            target = discover_dir / f"{safe_name(playlist)}.m3u8"
            try:
                if target.exists():
                    target.unlink()
                    removed_files += 1
            except OSError as e:
                log.warning("删除过期歌单文件失败 %s: %s", target, e)
        log.info("已清理过期自动歌单 %d 个（Navidrome 歌单删除 %d，歌单文件删除 %d，音频文件保留）",
                 len(candidates), navi_deleted, removed_files)
        return {"candidates": len(candidates), "navi_deleted": navi_deleted,
                "files_deleted": removed_files}

    def _aggregate_discover(self, tracks: list[Track]) -> list[Track]:
        """聚合推荐源曲目 -> 每日发现歌单。

        规则：
        - 网易云日推原样保留（全部进自己的日推歌单，不受限额）；
        - 其余来源（ListenBrainz 每周歌单/CF、Last.fm 等）合并为"每日发现-{today}"，
          多源重复推荐叠加加分；已收过的曲目（tracks 表 downloaded/existed）剔除，
          不占当日名额；按分数取前 daily_discover_limit 首（失败过的可再进，走重试）。
        """
        today = datetime.date.today().isoformat()
        daily = [t for t in tracks if t.origin == "netease_daily"]
        pool = [t for t in tracks if t.origin != "netease_daily"]

        merged: dict[str, Track] = {}
        for t in pool:
            k = track_key(t.artists, t.title)
            if k in merged:
                old = merged[k]
                old.score = max(old.score, t.score) + 0.1
                old.origin = f"{old.origin},{t.origin}" if t.origin not in old.origin else old.origin
                old.ncm_id = old.ncm_id or t.ncm_id
            else:
                merged[k] = t

        known = 0
        for k, t in list(merged.items()):
            row = self.db.get_track(k)
            if row and row["status"] in ("downloaded", "existed"):
                known += 1
                del merged[k]

        selected = sorted(merged.values(), key=lambda t: (-t.score, t.title))[: self.cfg.daily_discover_limit]
        for t in selected:
            t.playlist = f"{DAILY_DISCOVER_NAME}-{today}"

        log.info("推荐聚合: 日推 %d 首（不限额）；其他源 %d 首去重后 %d，已收过剔除 %d，每日发现取前 %d 首",
                 len(daily), len(pool), len(merged) + known, known, len(selected))
        return daily + selected

    # ---------- 听歌回传 ----------

    def _scrobble_recent(self) -> dict:
        """从 ListenBrainz 拉取近期播放记录，回传到网易云，返回 {ok, count, errors}。"""
        sc = self.cfg.sources.get("listenbrainz")
        if not sc or not sc.enabled:
            return {"ok": False, "msg": "ListenBrainz 未启用"}
        username = sc.extra.get("username", "")
        if not username:
            return {"ok": False, "msg": "未配置 ListenBrainz 用户名"}
        if self.last_cookie_ok is False:
            return {"ok": False, "msg": "网易云 Cookie 无效"}
        if self.last_cookie_ok is not True:
            return {"ok": False, "msg": "网易云 API 暂时不可用，无法校验 Cookie"}

        last_ts = float(self.db.get_property(SCROBBLE_TS_KEY, "0"))
        try:
            pending = set(json.loads(self.db.get_property(SCROBBLE_PENDING_KEY, "[]")))
        except (TypeError, ValueError):
            pending = set()
        pending_times = []
        for item in pending:
            try:
                pending_times.append(float(item.split("|", 1)[0]))
            except (ValueError, IndexError):
                continue
        fetch_ts = min([last_ts, *(t - 1 for t in pending_times)]) if pending_times else last_ts
        listens = get_recent_listens(username, min_ts=fetch_ts)

        if not listens:
            return {"ok": True, "count": 0, "msg": f"无新记录（上次: {int(last_ts)}）"}

        success, fail, max_ts = 0, 0, last_ts
        for l in listens:
            listen_key = f"{l['listened_at']}|{l['artist']}|{l['title']}"
            if l["listened_at"] <= last_ts and listen_key not in pending:
                continue
            try:
                self.scrobble_limiter.wait()
                candidates = self.ncm.search(f"{l['artist']} {l['title']}", limit=5)
                track = Track(title=l["title"], artists=[l["artist"]],
                              duration_ms=l.get("duration_ms", 0))
                hit = matcher.best_match(track, candidates,
                                         self.cfg.title_threshold, self.cfg.max_duration_diff)
                if not hit:
                    # 宽松一点再试一次
                    track2 = Track(title=l["title"], artists=l["artist"].split("/"))
                    hit = matcher.best_match(track2, candidates,
                                             self.cfg.title_threshold - 5, self.cfg.max_duration_diff + 5)
                if not hit:
                    fail += 1
                    pending.add(listen_key)
                    continue
                time_ms = l.get("duration_ms", 180000) or 180000
                self.scrobble_limiter.wait()
                if self.ncm.scrobble(hit["id"], time_ms):
                    success += 1
                    if l["listened_at"] > max_ts:
                        max_ts = l["listened_at"]
                else:
                    fail += 1
                    pending.add(listen_key)
                    continue
                pending.discard(listen_key)
            except Exception as e:
                log.debug("听歌打卡失败 %s - %s: %s", l["artist"], l["title"], e)
                fail += 1
                pending.add(listen_key)

        if max_ts > last_ts:
            self.db.set_property(SCROBBLE_TS_KEY, str(max_ts))
        self.db.set_property(SCROBBLE_PENDING_KEY, json.dumps(sorted(pending), ensure_ascii=False))
        skipped = len(listens) - success - fail
        log.info("听歌回传: %d 成功, %d 失败（跳过 %d 首）", success, fail, skipped)
        return {"ok": fail == 0, "count": success,
                "fail": fail, "total": len(listens)}

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
            self.refresh_cookie_status()
            stats["cookie_ok"] = self.last_cookie_ok
            if self.last_cookie_ok is False:
                log.warning("网易云 Cookie 无效或未配置：日推/完整歌单不可用，搜索与免费音源仍可用")
            elif self.last_cookie_ok is None:
                log.warning("无法连接网易云 API，暂不判断 Cookie 状态")

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
                if source.name.startswith("netease") and self.last_cookie_ok is not True:
                    reason = "cookie" if self.last_cookie_ok is False else "api_unavailable"
                    log.warning("跳过源 %s（%s）", source.name, reason)
                    stats["sources"][source.name] = f"skipped({reason})"
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

            # 推荐聚合：日推不限额全收；其余源合并为"每日发现"歌单并按分数限额
            capped = self._aggregate_discover(discover_tracks)

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
            self._cleanup_old_playlists()

            # 6. 听歌回传到网易云
            try:
                scrobble_stats = self._scrobble_recent()
                stats["scrobble"] = scrobble_stats
            except Exception as e:
                log.warning("听歌回传异常: %s", e)
                stats["scrobble"] = {"ok": False, "msg": str(e)}

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
            self._cleanup_tmp()


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
