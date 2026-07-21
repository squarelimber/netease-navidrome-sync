"""Last.fm 派生推荐源：近期常听 + 最爱 -> 相似歌曲聚合。"""

import datetime
import logging

import requests

from .base import Source, Track
from ..util import RateLimiter, track_key

log = logging.getLogger(__name__)

API = "https://ws.audioscrobbler.com/2.0/"


class LastFmSource(Source):
    name = "lastfm"

    def __init__(self, api_key: str, username: str, max_tracks: int = 40,
                 seed_limit: int = 20, similar_per_seed: int = 5):
        self.api_key = api_key
        self.username = username
        self.max_tracks = max_tracks
        self.seed_limit = seed_limit
        self.similar_per_seed = similar_per_seed
        self.session = requests.Session()
        self.limiter = RateLimiter(0.25)  # 礼貌限速

    def _call(self, **params) -> dict:
        self.limiter.wait()
        params.update({"api_key": self.api_key, "format": "json"})
        resp = self.session.get(API, params=params, timeout=20)
        resp.raise_for_status()
        return resp.json()

    def _top_tracks(self) -> list[dict]:
        data = self._call(method="user.getTopTracks", user=self.username,
                          period="1month", limit=self.seed_limit)
        return (data.get("toptracks") or {}).get("track", []) or []

    def _loved_tracks(self) -> list[dict]:
        data = self._call(method="user.getLovedTracks", user=self.username,
                          limit=self.seed_limit)
        return (data.get("lovedtracks") or {}).get("track", []) or []

    def _recent_keys(self) -> set:
        """近期已听曲目（避免推荐刚听过的）。"""
        try:
            data = self._call(method="user.getRecentTracks", user=self.username, limit=100)
            keys = set()
            for t in (data.get("recenttracks") or {}).get("track", []) or []:
                keys.add(track_key([(t.get("artist") or {}).get("#text", "")], t.get("name", "")))
            return keys
        except Exception as e:
            log.debug("获取 Last.fm 近期记录失败: %s", e)
            return set()

    def _similar(self, artist: str, title: str) -> list[dict]:
        try:
            data = self._call(method="track.getSimilar", artist=artist,
                              track=title, limit=self.similar_per_seed,
                              autocorrect=1)
            return (data.get("similartracks") or {}).get("track", []) or []
        except Exception as e:
            log.debug("相似歌曲获取失败 %s - %s: %s", artist, title, e)
            return []

    def fetch(self) -> list[Track]:
        today = datetime.date.today().isoformat()
        recent = self._recent_keys()

        # 种子：常听(权重1.0) + 最爱(权重0.9)，去重
        seeds = {}
        for t in self._top_tracks():
            k = track_key([t.get("artist", {}).get("name", "")], t.get("name", ""))
            seeds[k] = (t, 1.0)
        for t in self._loved_tracks():
            artist = (t.get("artist") or {}).get("name", "")
            k = track_key([artist], t.get("name", ""))
            seeds.setdefault(k, (t, 0.9))

        # 聚合相似曲目得分
        scores = {}   # key -> score
        info = {}     # key -> (title, [artists])
        for seed, weight in seeds.values():
            s_artist = seed.get("artist") or {}
            s_artist_name = s_artist.get("name") or s_artist.get("#text", "")
            s_title = seed.get("name", "")
            if not s_artist_name or not s_title:
                continue
            for sim in self._similar(s_artist_name, s_title):
                title = sim.get("name", "")
                artist = (sim.get("artist") or {}).get("name", "")
                if not title or not artist:
                    continue
                k = track_key([artist], title)
                if k in recent or k in seeds:
                    continue
                try:
                    match = float(sim.get("match", 0.5))
                except (TypeError, ValueError):
                    match = 0.5
                scores[k] = scores.get(k, 0) + match * weight
                info[k] = (title, [artist])

        if not scores:
            log.info("Last.fm 无新推荐")
            return []
        top = sorted(scores.items(), key=lambda x: -x[1])[: self.max_tracks]
        max_score = top[0][1] or 1
        tracks = [
            Track(title=info[k][0], artists=info[k][1],
                  origin=self.name, score=round(v / max_score, 3),
                  playlist=f"LastFM-推荐-{today}")
            for k, v in top
        ]
        log.info("Last.fm 派生推荐: %d 首（种子 %d 个）", len(tracks), len(seeds))
        return tracks
