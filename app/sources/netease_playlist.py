"""网易云指定歌单同步源（如"我喜欢的音乐"）。"""

import logging

from .base import Source, Track

log = logging.getLogger(__name__)


class NeteasePlaylistSource(Source):
    name = "netease_playlists"

    def __init__(self, ncm_api, playlists: list):
        """playlists: [{"name": ..., "id": ...}]"""
        self.api = ncm_api
        self.playlists = playlists

    def fetch(self) -> list[Track]:
        tracks = []
        for pl in self.playlists:
            pid, pname = pl.get("id"), pl.get("name", str(pl.get("id")))
            try:
                detail = self.api.get_playlist_detail(pid)
                songs = self.api.get_song_details(detail["track_ids"])
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
