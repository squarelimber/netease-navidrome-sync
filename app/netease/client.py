"""网易云音乐 API 客户端。

- 普通 GET：歌单详情、歌曲详情、歌词、outer url 音频
- weapi POST：每日推荐、搜索（需要 Cookie 登录态）
"""

import json
import logging
import time

import requests

from . import weapi

log = logging.getLogger(__name__)

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)


class NCMApiError(Exception):
    pass


class CookieInvalidError(NCMApiError):
    pass


class NCMApi:
    def __init__(self, cookie: str = "", timeout: int = 15):
        self.cookie = cookie
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": UA,
                "Referer": "https://music.163.com/",
                "Origin": "https://music.163.com",
                "Cookie": cookie,
            }
        )
        self.timeout = timeout

    # ---------- 底层 ----------

    @property
    def _csrf(self) -> str:
        for part in self.cookie.split(";"):
            part = part.strip()
            if part.startswith("__csrf="):
                return part[len("__csrf="):]
        return ""

    def _post_weapi(self, path: str, payload: dict) -> dict:
        payload["csrf_token"] = self._csrf
        data = weapi.encrypt(payload)
        url = f"https://music.163.com/weapi/{path}?csrf_token={self._csrf}"
        resp = self.session.post(url, data=data, timeout=self.timeout)
        resp.raise_for_status()
        return resp.json()

    def _get(self, url: str, **kwargs) -> requests.Response:
        resp = self.session.get(url, timeout=self.timeout, **kwargs)
        resp.raise_for_status()
        return resp

    # ---------- 账号 ----------

    def check_cookie(self) -> bool:
        """检查 Cookie 是否有效（是否处于登录态）。"""
        if not self.cookie:
            return False
        try:
            data = self._post_weapi("w/nuser/account/get", {})
            return data.get("code") == 200 and bool(data.get("account"))
        except Exception as e:
            log.warning("Cookie 检查失败: %s", e)
            return False

    # ---------- 歌单 ----------

    def get_playlist_detail(self, playlist_id) -> dict:
        """返回 {id, name, creator, track_ids}。未登录只能拿到前 10 首的完整信息。"""
        resp = self._get(f"https://music.163.com/api/v6/playlist/detail?id={playlist_id}")
        data = resp.json()
        if data.get("code") != 200 or not data.get("playlist"):
            raise NCMApiError(f"获取歌单失败: code={data.get('code')}")
        pl = data["playlist"]
        return {
            "id": pl["id"],
            "name": pl["name"],
            "creator": (pl.get("creator") or {}).get("nickname", ""),
            "track_ids": [t["id"] for t in pl.get("trackIds", [])],
        }

    # ---------- 歌曲 ----------

    @staticmethod
    def _norm_song(s: dict) -> dict:
        return {
            "id": s["id"],
            "name": s.get("name", ""),
            "artists": [a.get("name", "") for a in s.get("artists", s.get("ar", []))],
            "album": (s.get("album") or s.get("al") or {}).get("name", ""),
            "pic_url": (s.get("album") or s.get("al") or {}).get("picUrl", ""),
            "duration_ms": s.get("duration", s.get("dt", 0)),
        }

    def get_song_details(self, ids: list) -> list:
        """批量获取歌曲详情，自动分批。"""
        songs = []
        for i in range(0, len(ids), 500):
            batch = ids[i:i + 500]
            resp = self._get(
                "https://music.163.com/api/song/detail/",
                params={"ids": json.dumps(batch)},
            )
            data = resp.json()
            if data.get("code") != 200:
                raise NCMApiError(f"获取歌曲详情失败: code={data.get('code')}")
            songs.extend(self._norm_song(s) for s in data.get("songs", []))
            time.sleep(0.3)
        return songs

    def get_song_detail(self, song_id: int) -> dict:
        songs = self.get_song_details([song_id])
        if not songs:
            raise NCMApiError(f"歌曲不存在: {song_id}")
        return songs[0]

    # ---------- 歌词 ----------

    def get_lyrics(self, song_id: int):
        """返回 (原文歌词, 翻译歌词)，均无则 (None, None)。"""
        try:
            resp = self._get(
                "https://music.163.com/api/song/lyric",
                params={"id": song_id, "lv": 1, "kv": 1, "tv": -1},
            )
            data = resp.json()
        except Exception as e:
            log.debug("获取歌词失败(%s): %s", song_id, e)
            return None, None
        olrc = (data.get("lrc") or {}).get("lyric") or None
        tlrc = (data.get("tlyric") or {}).get("lyric") or None
        return olrc, tlrc

    # ---------- 搜索 ----------

    def search(self, keyword: str, limit: int = 10) -> list:
        """搜索单曲。优先 weapi 云搜索（需登录态），失败回退经典接口（无需登录）。"""
        if self.cookie:
            try:
                data = self._post_weapi(
                    "cloudsearch/get/web",
                    {"s": keyword, "type": 1, "limit": limit, "offset": 0, "total": True},
                )
                if data.get("code") == 200:
                    songs = (data.get("result") or {}).get("songs", [])
                    if songs:
                        return [self._norm_song(s) for s in songs]
                log.debug("weapi 搜索不可用(code=%s)，回退经典接口", data.get("code"))
            except Exception as e:
                log.debug("weapi 搜索失败，回退经典接口: %s", e)
        try:
            resp = self.session.post(
                "https://music.163.com/api/search/get",
                data={"s": keyword, "type": 1, "limit": limit, "offset": 0},
                timeout=self.timeout,
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            log.warning("网易云搜索失败: %s", e)
            return []
        return [self._norm_song(s) for s in (data.get("result") or {}).get("songs", [])]

    # ---------- 每日推荐 ----------

    def get_daily_recommend(self) -> list:
        """每日推荐歌曲（需登录态），返回标准化歌曲列表。"""
        data = self._post_weapi("v3/discovery/recommend/songs", {})
        if data.get("code") != 200:
            raise CookieInvalidError(f"获取日推失败 code={data.get('code')}（Cookie 可能已失效）")
        songs = (data.get("data") or {}).get("dailySongs", [])
        return [self._norm_song(s) for s in songs]

    # ---------- 音频（免费外链） ----------

    def get_outer_audio(self, song_id: int) -> bytes | None:
        """官方 outer url 免费音源。VIP 歌曲返回 HTML，此处返回 None。"""
        try:
            resp = self._get(
                f"https://music.163.com/song/media/outer/url?id={song_id}.mp3",
                allow_redirects=True,
                stream=True,
            )
        except Exception as e:
            log.debug("outer url 请求失败(%s): %s", song_id, e)
            return None
        content_type = resp.headers.get("Content-Type", "")
        if "text/html" in content_type:
            return None
        content = resp.content
        if len(content) < 100 * 1024:  # 小于 100KB 基本不可能是完整歌曲
            return None
        return content
