"""api-enhanced HTTP 客户端。

将 app/netease/ 中的全部网易云操作委托给 api-enhanced 后端。
"""

import logging

import requests

log = logging.getLogger(__name__)

TIMEOUT = 25


class NCMAPIClient:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "navidrome-sync/0.1"})
        self._cookie = ""

    @property
    def cookie(self) -> str:
        return self._cookie

    def set_cookie(self, cookie: str):
        self._cookie = cookie
        log.info("Cookie 已更新（%d bytes）", len(cookie))

    def _get(self, path: str, **params) -> dict:
        if self._cookie:
            params["cookie"] = self._cookie
        try:
            r = self.session.get(f"{self.base_url}{path}", params=params, timeout=TIMEOUT)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            log.warning("api-enhanced 请求失败 %s: %s", path, e)
            return {"code": -1, "msg": str(e)}

    # ------- 登录 -------

    def login_qr_key(self) -> dict:
        """获取二维码 unikey。返回 {ok, key, qrurl}。"""
        j = self._get("/login/qr/key")
        if j.get("code") != 200:
            return {"ok": False, "msg": f"获取 unikey 失败: {j}"}
        d = j.get("data", {})
        return {"ok": True, "key": d.get("unikey", ""), "qrurl": d.get("qrurl", "")}

    def login_qr_create(self, key: str, platform: str = "web", qrimg: bool = True) -> dict:
        """生成二维码图片。返回 {ok, qrurl, qrimg}（base64 PNG data URL）。"""
        j = self._get("/login/qr/create", key=key, platform=platform, qrimg="true" if qrimg else "")
        if j.get("code") != 200:
            return {"ok": False, "msg": f"生成二维码失败: {j}"}
        d = j.get("data", {})
        return {"ok": True, "qrurl": d.get("qrurl", ""), "qrimg": d.get("qrimg", "")}

    def login_qr_check(self, key: str) -> dict:
        """轮询二维码状态。成功时 cookie 为完整登录态。"""
        j = self._get("/login/qr/check", key=key)
        return {"status": j.get("code", 0), "cookie": j.get("cookie", ""),
                "msg": j.get("message", ""), "raw": j}

    # ------- 搜索 -------

    def search(self, keywords: str, limit: int = 30, offset: int = 0) -> list:
        """搜索单曲，返回标准化列表。"""
        j = self._get("/cloudsearch", keywords=keywords, limit=limit, offset=offset,
                       type=1)
        if j.get("code") != 200:
            return []
        songs = (j.get("result") or {}).get("songs", [])
        return [self._norm_song(s) for s in songs]

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

    # ------- 歌曲信息 -------

    def song_detail(self, song_ids: list) -> list:
        j = self._get("/song/detail", ids=",".join(str(i) for i in song_ids))
        if j.get("code") != 200:
            return []
        return [self._norm_song(s) for s in (j.get("songs") or [])]

    def lyric(self, song_id: int) -> tuple[str | None, str | None]:
        """返回 (原文, 翻译)。"""
        j = self._get("/lyric", id=song_id)
        if j.get("code") != 200:
            return None, None
        olrc = (j.get("lrc") or {}).get("lyric") or None
        tlrc = (j.get("tlyric") or {}).get("lyric") or None
        return olrc, tlrc

    # ------- 歌单 -------

    def playlist_detail(self, playlist_id: int) -> dict:
        j = self._get("/playlist/detail", id=playlist_id)
        if j.get("code") != 200:
            return {}
        pl = j.get("playlist") or {}
        return {
            "id": pl.get("id"),
            "name": pl.get("name", ""),
            "creator": (pl.get("creator") or {}).get("nickname", ""),
            "track_ids": [t["id"] for t in (pl.get("trackIds") or [])],
        }

    # ------- 日推 -------

    def daily_recommend(self) -> list:
        j = self._get("/recommend/songs")
        if j.get("code") != 200:
            return []
        return [self._norm_song(s)
                for s in ((j.get("data") or {}).get("dailySongs") or [])]

    # ------- 账号 -------

    def check_cookie(self) -> bool:
        if not self._cookie:
            return False
        j = self._get("/login/status")
        return j.get("code") == 200 and bool((j.get("data") or {}).get("account"))
