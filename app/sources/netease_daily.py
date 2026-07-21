"""网易云每日推荐源。"""

import datetime
import logging

from .base import Source, Track

log = logging.getLogger(__name__)


class NeteaseDailySource(Source):
    name = "netease_daily"

    def __init__(self, ncm_api):
        self.api = ncm_api

    def fetch(self) -> list[Track]:
        songs = self.api.get_daily_recommend()
        today = datetime.date.today().isoformat()
        tracks = []
        for i, s in enumerate(songs):
            tracks.append(Track(
                title=s["name"], artists=s["artists"], album=s["album"],
                duration_ms=s["duration_ms"], ncm_id=s["id"],
                origin=self.name, score=1.0 - i * 0.005,
                playlist=f"网易云日推-{today}",
            ))
        log.info("网易云日推: %d 首", len(tracks))
        return tracks
