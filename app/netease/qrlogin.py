"""网易云登录（委托 api-enhanced 后端）。

扫码 + 手机号登录，成功后回调 on_success(cookie) 注入运行中实例。
"""

import logging
from typing import Callable

from ..api_client import NCMAPIClient

log = logging.getLogger(__name__)

_qr_sessions: dict[str, bool] = {}


class LoginHandler:
    def __init__(self, api: NCMAPIClient, on_success: Callable[[str], None]):
        self.api = api
        self.on_success = on_success

    # ------- 扫码登录 -------

    def qr_start(self) -> dict:
        # 1. 获取 unikey
        r = self.api.login_qr_key()
        if not r.get("ok"):
            return r
        key = r["key"]
        # 2. 通过 api-enhanced 生成二维码 PNG（base64）
        cr = self.api.login_qr_create(key, platform="web")
        if not cr.get("ok"):
            return cr
        _qr_sessions[key] = True
        return {"ok": True, "key": key,
                "qrimg": cr.get("qrimg", ""),
                "qrurl": cr.get("qrurl", "")}

    def qr_poll(self, key: str) -> dict:
        if key not in _qr_sessions:
            return {"status": 800}
        r = self.api.login_qr_check(key)
        status = r.get("status", 0)
        if status == 803:
            cookie = r.get("cookie", "").strip()
            if cookie:
                self.on_success(cookie)
                _qr_sessions.pop(key, None)
                log.info("扫码登录成功")
                return {"status": 803, "ok": True}
            log.warning("扫码 803 但无 Cookie: raw=%s", r.get("raw"))
        return r

    # ------- 手机号登录 -------

    def phone_login(self, phone: str, password: str) -> dict:
        r = self.api.login_cellphone(phone, password)
        if r.get("ok"):
            self.on_success(r["cookie"])
        return r
