"""api-enhanced HTTP 客户端。

将 app/netease/ 中的全部网易云操作委托给 api-enhanced 后端。
"""

from __future__ import annotations

import base64
import json
import logging
import random
import re
import string
import time

import requests

try:
    from Crypto.Cipher import AES
    from Crypto.PublicKey import RSA
    from Crypto.Util.Padding import pad
    _HAS_CRYPTO = True
except ImportError:  # pycryptodome 缺失时仍可用 ncm-api 回传路径
    _HAS_CRYPTO = False

log = logging.getLogger(__name__)

TIMEOUT = 25
_TRANSIENT_HTTP_STATUS = frozenset({408, 425, 429, 500, 502, 503, 504})
_REQUEST_RETRY_ATTEMPTS = 2
_REQUEST_RETRY_DELAY = 2.0

# ---- weapi 加密常量（逐行对齐 NeteaseCloudMusicApi util/crypto.js + request.js）----
_WEAPI_PRESET_KEY = "0CoJUm6Qyw8W8jud"
_WEAPI_IV = "0102030405060708"
_WEAPI_BASE62 = (string.ascii_lowercase + string.ascii_uppercase + string.digits)
_WEAPI_PUBLIC_KEY = (
    "-----BEGIN PUBLIC KEY-----\n"
    "MIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQKBgQDgtQn2JZ34ZC28NWYpAUd98iZ37BUrX/aKzmFbt7clFSs6sXqHauqKWqdtLkF2KexO40H1YTX8z2lSgBBOAxLsvaklV8k4cBFK9snQXE9/DDaFt6Rr7iVZMldczhC0JNgTz+SHXT6CBHuX3e9SdB1Ua44oncaTWz7OBGLbCiK45wIDAQAB\n"
    "-----END PUBLIC KEY-----\n"
)
_MUSIC_HOST = "https://music.163.com"
_WEAPI_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/86.0.4240.30 Safari/537.36"
)


def _weapi_encrypt(data: dict, cookie: str = "", _secret_key: str | None = None) -> dict:
    """weapi 加密，返回 {params, encSecKey}。

    逐行对齐 NeteaseCloudMusicApi util/crypto.js + util/request.js：
    明文 = JSON({...data, csrf_token})，csrf_token 取自 Cookie 的 _csrf
    （无则为空串），无 {os,data} 包裹；双层 AES-CBC：内层用固定 preset key，
    外层用 16 位 base62 secret key，外层输入为内层密文的 base64 字符串；
    encSecKey = RSA 无填充（前置 112 个 0 字节）加密反转后的 secret key，
    小写 hex。表单字段是 params（复数），请求必须发到 /weapi/ 前缀 URL。
    """
    m = re.search(r"_csrf=([^(;|$)]+)", cookie or "")
    payload = dict(data)
    payload["csrf_token"] = m.group(1) if m else ""
    text = json.dumps(payload, separators=(",", ":"))
    secret_key = _secret_key or "".join(random.choice(_WEAPI_BASE62) for _ in range(16))

    def _aes(plain: bytes, key: str) -> bytes:
        cipher = AES.new(key.encode("utf-8"), AES.MODE_CBC, _WEAPI_IV.encode("utf-8"))
        return cipher.encrypt(pad(plain, 16))

    inner_b64 = base64.b64encode(_aes(text.encode("utf-8"), _WEAPI_PRESET_KEY)).decode("ascii")
    params = base64.b64encode(_aes(inner_b64.encode("ascii"), secret_key)).decode("ascii")
    pub = RSA.import_key(_WEAPI_PUBLIC_KEY)
    block = b"\x00" * (128 - len(secret_key)) + secret_key[::-1].encode("utf-8")
    raw = pow(int.from_bytes(block, "big"), pub.e, pub.n).to_bytes(128, "big")
    return {"params": params, "encSecKey": raw.hex()}


class NCMAPIClient:
    def __init__(self, base_url: str, music_host: str | None = None):
        self.base_url = base_url.rstrip("/")
        # 网易云直连 host；空串表示禁用直连路径（容器无法访问公网时只走 ncm-api）
        self.music_host = _MUSIC_HOST if music_host is None else music_host
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
            # 不要记录 requests 异常对象本身：其字符串通常包含完整 URL 和 Cookie。
            log.warning("api-enhanced 请求失败 %s (HTTP %s): %s | %s",
                        path, status, type(e).__name__, snippet)
            return {"code": -1, "msg": str(e), "_request_error": True,
                    "_http_status": status, "_error_snippet": snippet}
        except ValueError as e:
            log.warning("api-enhanced 响应不是合法 JSON %s: %s", path, e)
            return {"code": -1, "msg": str(e)}

    @staticmethod
    def _is_transient_response(data: dict) -> bool:
        """判断是否值得短暂退避后重试。"""
        status = data.get("_http_status")
        if status in _TRANSIENT_HTTP_STATUS:
            return True
        text = " ".join(str(data.get(key) or "") for key in
                         ("msg", "message", "_error_snippet")).lower()
        # 网易云常用 HTTP 405 返回“操作频繁”，它不是方法错误，而是频控响应。
        return any(marker in text for marker in (
            "操作频繁", "请求频繁", "too many requests", "rate limit",
            "socket disconnected", "temporarily unavailable",
        ))

    def _get_retry(self, path: str, **params) -> dict:
        """对搜索/回传等易受频控影响的请求做一次短退避重试。"""
        result = {}
        for attempt in range(_REQUEST_RETRY_ATTEMPTS):
            result = self._get(path, **params)
            if result.get("code") == 200:
                return result
            if attempt + 1 >= _REQUEST_RETRY_ATTEMPTS or not self._is_transient_response(result):
                return result
            log.info("api-enhanced %s 暂时失败，%.1f 秒后重试 (%d/%d)",
                     path, _REQUEST_RETRY_DELAY, attempt + 1,
                     _REQUEST_RETRY_ATTEMPTS - 1)
            time.sleep(_REQUEST_RETRY_DELAY)
        return result

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
        j = self._get_retry("/cloudsearch", keywords=keywords, limit=limit,
                            offset=offset, type=1)
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

    # ------- 最近播放 -------

    @staticmethod
    def _norm_recent_song(item: dict) -> dict:
        """归一化『最近播放』条目。

        真实结构：{resourceId, playTime, resourceType, data:{歌曲详情}, banned,
        multiTerminalInfo}。歌曲详情在 data 内，兼容 data 再包一层 song 的情况，
        也兼容直接结构（id/name/ar/al/dt）作为兜底。
        """
        s = item.get("data") if isinstance(item.get("data"), dict) else item
        if isinstance(s.get("song"), dict):
            s = s["song"]
        artists = s.get("artists") or s.get("ar") or []
        album = s.get("album") or s.get("al") or {}
        t = item.get("playTime") or item.get("time") or s.get("time") or 0
        if isinstance(t, (int, float)) and t > 1e12:  # 毫秒 → 秒
            t = t / 1000
        return {
            "id": item.get("resourceId") or s.get("id"),
            "title": s.get("name", ""),
            "artists": [a.get("name", "") for a in artists],
            "album": album.get("name", "") if isinstance(album, dict) else str(album or ""),
            "duration_ms": s.get("dt") or s.get("duration") or 0,
            "time": int(t),
        }

    def recent_songs(self, limit: int = 100) -> list:
        """拉取网易云最近播放列表（经 ncm-api 的 /record/recent/song 端点）。

        直连的 /api/song/list/recent 已下线（code=404），且『最近播放』并非
        /user/playlist 里的歌单，故走 ncm-api 专用的 /record/recent/song。
        返回 [{id, title, artists, album, duration_ms, time}, ...]，
        time 为播放时间戳（秒）。登录态无效或无播放记录时返回空/抛异常。
        """
        j = self._get("/record/recent/song", limit=limit)
        if j.get("_request_error"):
            raise RuntimeError("获取最近播放失败：ncm-api 不可用")
        if j.get("code") != 200:
            raise RuntimeError(f"获取最近播放失败: code={j.get('code')}")
        data = j.get("data") or {}
        songs = data.get("list") or []
        if songs:
            first = songs[0]
            inner = first.get("data")
            log.info("最近播放核对: total=%s 条目keys=%s data_keys=%s",
                     data.get("total"), list(first.keys()),
                     list(inner.keys()) if isinstance(inner, dict) else type(inner).__name__)
            norm0 = self._norm_recent_song(first)
            log.info("最近播放核对: 首条解析 id=%s title=%r artists=%s duration_ms=%s time=%s",
                     norm0["id"], norm0["title"], norm0["artists"],
                     norm0["duration_ms"], norm0["time"])
        return [self._norm_recent_song(s) for s in songs[:limit]]

    # ------- 账号 -------

    def check_cookie(self) -> bool:
        """检查 Cookie 是否有效；网络不可用时仍返回 False 以兼容旧调用方。"""
        return self.check_cookie_state() is True

    def check_cookie_state(self) -> bool | None:
        """返回 True=有效、False=明确失效、None=无法判断（网络/API 不可用）。"""
        if not self._cookie:
            return False
        j = self._get("/login/status")
        if j.get("_request_error"):
            return None
        data = j.get("data") or {}
        # api-enhanced 返回 {data: {code: 200, account, profile}}（顶层无 code），
        # 其他 fork 可能是顶层 code，两种都兼容
        ok = j.get("code") == 200 or data.get("code") == 200
        if not ok:
            return False
        account = data.get("account") or {}
        profile = data.get("profile") or {}
        # ncm-api 自带匿名账号（anonimousUser=true、profile=null）：
        # Cookie 未生效/失效时会落到它，必须判为未登录，否则会误报"已登录"
        if account.get("anonimousUser"):
            return False
        return bool(account or profile)

    # ------- 听歌打卡 -------

    def scrobble(self, song_id: int, time_ms: int = 180000) -> bool:
        """写入听歌记录（最近播放 + 听歌排行计数）。

        优先直连 music.163.com 的 /weapi/feedback/weblog（weapi 加密），绕开
        ncm-api 转发的 clientlog3.music.163.com（后者常被 403/TLS 拒连）。
        无 Cookie 或 pycryptodome 缺失时回退到 ncm-api /scrobble。
        """
        if self._cookie and _HAS_CRYPTO and self.music_host:
            try:
                if self._scrobble_direct(song_id, time_ms):
                    return True
            except requests.exceptions.RequestException as e:
                log.debug("直连 scrobble 失败，回退 ncm-api: %s", type(e).__name__)
        return self._scrobble_via_ncm(song_id, time_ms)

    def _scrobble_direct(self, song_id: int, time_ms: int) -> bool:
        """直连 music.163.com/weapi/feedback/weblog（weapi 加密）。"""
        body = {
            "logs": json.dumps([{
                "action": "play",
                "json": {
                    "download": 0,
                    "end": "playend",
                    "id": song_id,
                    "sourceId": song_id,
                    "time": time_ms,
                    "type": "song",
                    "wifi": 0,
                    "source": "list",
                },
            }], ensure_ascii=False),
        }
        payload = _weapi_encrypt(body, self._cookie)
        r = self.session.post(
            f"{self.music_host}/weapi/feedback/weblog",
            data=payload,
            headers={"User-Agent": _WEAPI_UA, "Referer": self.music_host,
                     "Cookie": self._cookie},
            timeout=TIMEOUT,
        )
        r.raise_for_status()
        return r.json().get("code") == 200

    def _scrobble_via_ncm(self, song_id: int, time_ms: int) -> bool:
        """经 ncm-api 回传（保留原重试逻辑，作为直连兜底）。"""
        j = self._get_retry("/scrobble", id=song_id, sourceid=song_id, time=time_ms)
        return j.get("code") == 200
