"""api-enhanced HTTP 客户端。

将 app/netease/ 中的全部网易云操作委托给 api-enhanced 后端。
"""

from __future__ import annotations

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
        url = f"{self.base_url}{path}"
        try:
            r = self.session.get(url, params=params, timeout=TIMEOUT)
            r.raise_for_status()
            return r.json()
        except requests.exceptions.RequestException as e:
            status = getattr(getattr(e, "response", None), "status_code", "?")
            snippet = ""
            resp = getattr(e, "response", None)
            if resp is not None:
                try:
                    snippet = (resp.text or "")[:200]
                except Exception:
                    pass
            log.warning("api-enhanced 请求失败 %s (HTTP %s): %s | %s",
                        path, status, e, snippet)
            return {"code": -1, "msg": str(e)}
        except ValueError as e:
            log.warning("api-enhanced 响应不是合法 JSON %s: %s", path, e)
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
        """按批查询歌曲详情（每批 200 个，避免 URL 过长）。"""
        out = []
        for i in range(0, len(song_ids), 200):
            chunk = song_ids[i:i + 200]
            j = self._get("/song/detail", ids=",".join(str(x) for x in chunk))
            if j.get("code") != 200:
                continue
            out.extend(self._norm_song(s) for s in (j.get("songs") or []))
        return out

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

    def playlist_track_all(self, playlist_id: int, limit: int = 1000, offset: int = 0) -> list:
        """分页拉取歌单全部曲目（/playlist/track/all，支持大歌单翻页）。"""
        j = self._get("/playlist/track/all", id=playlist_id, limit=limit, offset=offset)
        if j.get("code") != 200:
            return []
        return [self._norm_song(s) for s in (j.get("songs") or [])]

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
        data = j.get("data") or {}
        # api-enhanced 返回 {data: {code: 200, account, profile}}（顶层无 code），
        # 其他 fork 可能是顶层 code，两种都兼容
        ok = j.get("code") == 200 or data.get("code") == 200
        return ok and bool(data.get("account") or data.get("profile"))

    # ------- 听歌打卡 -------

    def scrobble(self, song_id: int, time_ms: int = 180000) -> bool:
        """写入听歌记录（最近播放 + 听歌排行计数）。"""
        j = self._get("/scrobble", id=song_id, sourceid=song_id, time=time_ms)
        return j.get("code") == 200
