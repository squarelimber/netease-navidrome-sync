"""网易云指定歌单同步源（如"我喜欢的音乐"）。"""

import logging

from .base import Source, Track

log = logging.getLogger(__name__)

PAGE_SIZE = 1000


class NeteasePlaylistSource(Source):
    name = "netease_playlists"

    def __init__(self, ncm_api, playlists: list):
        """playlists: [{"name": ..., "id": ...}]"""
        self.api = ncm_api
        self.playlists = playlists

    def _all_songs(self, pid: int) -> list:
        """翻页拉取歌单全部曲目；track/all 不可用时回退到 detail+song_detail。"""
        songs, seen = [], set()
        offset = 0
        while True:
            page = self.api.playlist_track_all(pid, limit=PAGE_SIZE, offset=offset)
            if not page:
                break
            for s in page:
                if s["id"] in seen:
                    continue
                seen.add(s["id"])
                songs.append(s)
            if len(page) < PAGE_SIZE:
                break
            offset += PAGE_SIZE
        if songs:
            return songs
        # 兜底：track/all 不存在或失败（部分 ncm-api 版本）
        detail = self.api.playlist_detail(pid)
        if detail.get("track_ids"):
            songs = self.api.song_detail(detail["track_ids"])
        return songs

    def fetch(self) -> list[Track]:
        tracks = []
        for pl in self.playlists:
            pid, pname = pl.get("id"), pl.get("name", str(pl.get("id")))
            try:
                songs = self._all_songs(pid)
            except Exception as e:
                log.error("获取歌单 %s(%s) 失败: %s", pname, pid, e)
                continue
            for i, s in enumerate(songs):
                tracks.append(Track(
                    title=s["name"], artists=s["artists"], album=s["album"],
                    duration_ms=s["duration_ms"], ncm_id=s["id"],
                    origin=f"playlist:{pname}", score=1.0,
                    playlist=pname,
                ))
            log.info("歌单 %s: %d 首", pname, len(songs))
        return tracks
