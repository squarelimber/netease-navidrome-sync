"""ListenBrainz 推荐源。

主路径：官方每周歌单（Weekly Jams / Weekly Exploration）——
        JSPF 已自带 title/artist/duration/MBID，无需查 MusicBrainz，更稳更快。
补充：CF 协同过滤原始推荐（仅返回 recording MBID，需 MusicBrainz 解析）。
"""

import datetime
import logging

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .base import Source, Track
from ..util import RateLimiter, safe_name

log = logging.getLogger(__name__)

LB_API = "https://api.listenbrainz.org/1"
MB_API = "https://musicbrainz.org/ws/2"


def _retry_session(total=3, backoff=1.5) -> requests.Session:
    s = requests.Session()
    retry = Retry(total=total, backoff_factor=backoff,
                 status_forcelist=[429, 500, 502, 503, 504], allowed_methods=["GET"])
    adapter = HTTPAdapter(max_retries=retry)
    s.mount("https://", adapter)
    s.mount("http://", adapter)
    s.headers["User-Agent"] = "navidrome-sync/0.1 ( self-hosted )"
    return s


def _jspf_artist(track: dict) -> list:
    cr = track.get("creator")
    if isinstance(cr, dict):
        name = cr.get("name") or ""
        return [name] if name else []
    if isinstance(cr, str):
        return [cr] if cr.strip() else []
    # 某些实现把艺术家放在 extension 里
    ext = track.get("extension") or {}
    mb_ext = ext.get("https://musicbrainz.org/doc/jspf#playlist", {}) or {}
    for key in ("artist", "artists"):
        v = mb_ext.get(key)
        if v:
            return v if isinstance(v, list) else [v]
    return []


def _extract_mbid(val) -> str:
    """从 identifier（可能是字符串或列表）提取最后一段 MBID。"""
    if isinstance(val, list):
        val = val[0] if val else ""
    if not isinstance(val, str) or not val:
        return ""
    return val.rstrip("/").split("/")[-1]


def _jspf_mbid(track: dict) -> str:
    return _extract_mbid(track.get("identifier"))


class ListenBrainzSource(Source):
    name = "listenbrainz"

    def __init__(self, username: str, max_playlists: int = 2,
                 cf_count: int = 30, use_mb: bool = True):
        self.username = username
        self.max_playlists = max_playlists
        self.cf_count = cf_count
        self.use_mb = use_mb  # 是否启用 CF 推荐（需 MusicBrainz 可达）
        self.session = _retry_session()
        self.mb_limiter = RateLimiter(1.1)

    def _get(self, url: str, timeout: int = 20):
        return self.session.get(url, timeout=timeout)

    # ---- 主路径：官方每周歌单 ----

    def _created_for_tracks(self) -> list[Track]:
        tracks: list[Track] = []
        try:
            resp = self._get(f"{LB_API}/user/{self.username}/playlists/createdfor")
            if resp.status_code != 200:
                log.info("LB 每周歌单列表不可用(%s)", resp.status_code)
                return []
            playlists = (resp.json().get("playlists") or [])[: self.max_playlists]
        except Exception as e:
            log.warning("LB 每周歌单列表获取失败: %s", e)
            return []

        for pl in playlists:
            info = pl.get("playlist") or pl
            if not isinstance(info, dict):
                continue
            pl_title = safe_name(info.get("title", f"ListenBrainz-{datetime.date.today()}"))
            pl_mbid = _extract_mbid(info.get("identifier"))
            if not pl_mbid:
                continue
            try:
                r = self._get(f"{LB_API}/playlist/{pl_mbid}")
                if r.status_code != 200:
                    continue
                trks = (r.json().get("playlist") or {}).get("track", []) or []
            except Exception as e:
                log.warning("LB 歌单 %s 详情获取失败: %s", pl_title, e)
                continue
            for t in trks:
                title = t.get("title") or ""
                artists = _jspf_artist(t)
                if not title or not artists:
                    continue
                dur = t.get("duration")
                try:
                    dur_ms = int(dur) if dur else 0
                except (TypeError, ValueError):
                    dur_ms = 0
                tracks.append(Track(
                    title=title, artists=artists, duration_ms=dur_ms,
                    origin=self.name, score=0.9, playlist=pl_title,
                    raw={"mbid": _jspf_mbid(t)},
                ))
            log.info("LB 歌单 %s 解析: %d 首", pl_title, len(trks))
        return tracks

    # ---- 补充：CF 推荐（需 MusicBrainz） ----

    def _resolve_mbid(self, mbid: str):
        self.mb_limiter.wait()
        try:
            resp = self._get(f"{MB_API}/recording/{mbid}",
                             params={"fmt": "json", "inc": "artists"})
            if resp.status_code != 200:
                return None
            data = resp.json()
            artists = [c["name"] for c in data.get("artist-credit", [])
                       if isinstance(c, dict) and "name" in c]
            return {"name": data.get("title", ""), "artists": artists,
                    "duration_ms": data.get("length") or 0}
        except Exception as e:
            log.debug("MusicBrainz 解析失败 %s: %s", mbid, e)
            return None

    def _cf_recs(self) -> list[Track]:
        if not self.use_mb:
            return []
        try:
            resp = self._get(f"{LB_API}/cf/recommendation/user/{self.username}/recording",
                             params={"count": self.cf_count})
            if resp.status_code != 200:
                return []
            items = (resp.json().get("payload") or {}).get("mbids", [])
        except Exception as e:
            log.warning("LB CF 推荐获取失败: %s", e)
            return []
        max_score = max((i.get("score", 1) for i in items), default=1) or 1
        seen = set()
        out = []
        for i in items:
            mbid = i["recording_mbid"]
            if mbid in seen:
                continue
            seen.add(mbid)
            info = self._resolve_mbid(mbid)
            if not info or not info["name"] or not info["artists"]:
                continue
            out.append(Track(
                title=info["name"], artists=info["artists"],
                duration_ms=info["duration_ms"], origin=self.name,
                score=0.6 + 0.4 * (i.get("score", 0) / max_score),
                playlist=f"ListenBrainz-CF-{datetime.date.today()}",
                raw={"mbid": mbid},
            ))
        return out

    def fetch(self) -> list[Track]:
        tracks = self._created_for_tracks()
        cf = self._cf_recs()
        # 去重：CF 中与每周歌单重复的不重复加入
        existing = {(t.title, tuple(t.artists)) for t in tracks}
        for t in cf:
            if (t.title, tuple(t.artists)) not in existing:
                tracks.append(t)
        log.info("ListenBrainz 推荐合计: %d 首（每周歌单 %d + CF %d）",
                 len(tracks), len(tracks) - len(cf), len(cf))
        return tracks