"""曲库组织：文件落盘、m3u8 歌单生成、Navidrome(Subsonic API) 查重。"""

from __future__ import annotations

import hashlib
import logging
import secrets
from pathlib import Path

import requests

from . import matcher
from .util import safe_name

log = logging.getLogger(__name__)


class SubsonicClient:
    """Navidrome 的 Subsonic API 客户端（仅用于查重）。"""

    def __init__(self, url: str, username: str, password: str):
        self.base = url.rstrip("/") + "/rest"
        self.u = username
        self.p = password

    def _params(self) -> dict:
        salt = secrets.token_hex(6)
        token = hashlib.md5((self.p + salt).encode()).hexdigest()
        return {
            "u": self.u, "t": token, "s": salt,
            "v": "1.16.1", "c": "navidrome-sync", "f": "json",
        }

    def search_songs(self, query: str, count: int = 10) -> list:
        try:
            resp = requests.get(
                f"{self.base}/search3.view",
                params={**self._params(), "query": query, "songCount": count,
                        "artistCount": 0, "albumCount": 0},
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()["subsonic-response"]
            if data.get("status") != "ok":
                log.warning("Subsonic 查询异常: %s", data.get("error"))
                return []
            return (data.get("searchResult3") or {}).get("song", []) or []
        except Exception as e:
            log.warning("Subsonic 查询失败: %s", e)
            return []

    def exists(self, track, title_threshold: int, max_duration_diff: int) -> bool:
        """曲库中是否已有该曲目。"""
        query = f"{track.artists[0] if track.artists else ''} {track.title}".strip()
        candidates = [
            {"name": s.get("title", ""),
             "artists": [s.get("artist", "")],
             "duration": s.get("duration", 0)}
            for s in self.search_songs(query)
        ]
        return matcher.best_match(track, candidates, title_threshold, max_duration_diff) is not None


def display_name(track) -> str:
    artists = ", ".join(track.artists) if track.artists else "Unknown"
    return safe_name(f"{artists} - {track.title}")


def write_lrc_sidecar(audio_path: Path, lrc_text: str | None):
    if not lrc_text:
        return
    lrc_path = audio_path.with_suffix(".lrc")
    try:
        lrc_path.write_text(lrc_text, encoding="utf-8")
    except Exception as e:
        log.warning("写入歌词文件失败: %s", e)


def write_m3u8(playlist_dir: Path, m3u_name: str, tracks_with_paths: list[tuple]):
    """在同目录生成 m3u8 歌单（条目为相对文件名）。

    tracks_with_paths: [(track_dict_or_obj, filename), ...]
    """
    playlist_dir.mkdir(parents=True, exist_ok=True)
    lines = ["#EXTM3U", f"#PLAYLIST:{m3u_name}"]
    for item, filename in tracks_with_paths:
        title = item["title"] if isinstance(item, dict) else item.title
        artists = item["artists"] if isinstance(item, dict) else item.artists
        if isinstance(artists, str):
            artists = [artists]
        lines.append(f"#EXTINF:-1,{', '.join(artists)} - {title}")
        lines.append(filename)
    path = playlist_dir / f"{safe_name(m3u_name)}.m3u8"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    log.info("已生成歌单文件 %s（%d 首）", path.name, len(tracks_with_paths))
    return path
