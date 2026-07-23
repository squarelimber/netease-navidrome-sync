"""网易云登录（委托 api-enhanced 后端）。

扫码 + 手机号登录，成功后回调 on_success(cookie) 注入运行中实例。
"""

import base64
import logging
from typing import Callable

from ..api_client import NCMAPIClient

log = logging.getLogger(__name__)

_qr_sessions: dict[str, dict] = {}


def _gen_qr_svg(text: str) -> str:
    try:
        import qrcode
        from io import BytesIO
        from qrcode.image.svg import SvgPathImage
        qr = qrcode.QRCode(border=2, image_factory=SvgPathImage)
        qr.add_data(text)
        qr.make(fit=True)
        buf = BytesIO()
        qr.make_image().save(buf)
        return buf.getvalue().decode("utf-8")
    except Exception as e:
        log.error("生成二维码失败: %s", e)
        return ""


class LoginHandler:
    def __init__(self, api: NCMAPIClient, on_success: Callable[[str], None]):
        self.api = api
        self.on_success = on_success

    # ------- 扫码登录 -------

    def qr_start(self) -> dict:
        r = self.api.login_qr_key()
        if not r.get("ok"):
            return r
        key = r["key"]
        qrurl = r.get("qrurl", f"https://music.163.com/login?codekey={key}")
        svg = _gen_qr_svg(qrurl)
        if not svg:
            return {"ok": False, "msg": "二维码生成失败"}
        _qr_sessions[key] = True
        return {"ok": True, "key": key, "svg": svg}

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
