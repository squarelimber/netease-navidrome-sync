"""网易云手机登录（扫码 + 手机号密码）。

扫码路径已被服务器封锁（code 8821），保留作为备用。
主力路径：手机号 + 密码 → weapi login/cellphone → 提取 Cookie。
"""

import hashlib
import logging
import time
from typing import Callable

import requests

from .weapi import encrypt

log = logging.getLogger(__name__)

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
QR_CONTENT = "https://music.163.com/login?codekey={key}"
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


def _extract_set_cookie(resp: requests.Response) -> str:
    parts = []
    for k, v in resp.headers.items():
        if k.lower() == "set-cookie":
            kv = v.split(";")[0] if ";" in v else v
            if "=" in kv:
                parts.append(kv)
    return "; ".join(parts)


class LoginHandler:
    def __init__(self, on_success: Callable[[str], None]):
        self.on_success = on_success

    # ------- 手机号+密码登录 -------

    def phone_login(self, phone: str, password: str) -> dict:
        """手机号+密码登录，成功则回调并返回 Cookie。"""
        md5_pwd = hashlib.md5(password.encode("utf-8")).hexdigest()
        session = requests.Session()
        session.headers.update({"User-Agent": UA, "Referer": "https://music.163.com/",
                                "Accept": "application/json, text/plain, */*"})
        try:
            data = encrypt({
                "phone": phone, "countrycode": "86",
                "password": md5_pwd, "rememberLogin": "true",
            })
            r = session.post(
                "https://music.163.com/weapi/login/cellphone",
                data=data, timeout=15,
            )
            j = r.json()
        except Exception as e:
            return {"ok": False, "msg": f"请求失败: {e}"}

        code = j.get("code", 0)
        if code == 200:
            cookie = (j.get("cookie") or "").strip() or _extract_set_cookie(r)
            if cookie:
                self.on_success(cookie)
                return {"ok": True, "msg": "登录成功"}
            return {"ok": False, "msg": "登录成功但未收到 Cookie", "raw": j}
        msg = j.get("message") or j.get("msg", str(j))
        return {"ok": False, "msg": msg, "raw": j}

    # ------- 扫码登录（已失效） -------

    def qr_start(self) -> dict:
        session = requests.Session()
        session.headers.update({"User-Agent": UA, "Referer": "https://music.163.com/"})
        try:
            data = encrypt({"type": 1})
            r = session.post(
                "https://music.163.com/weapi/login/qrcode/unikey",
                data=data, timeout=15,
            )
            j = r.json()
            if j.get("code") != 200 or not j.get("unikey"):
                return {"ok": False, "msg": f"获取 unikey 失败: {j}"}
            key = j["unikey"]
        except Exception as e:
            return {"ok": False, "msg": f"请求失败: {e}"}
        _qr_sessions[key] = {"session": session, "t": time.time()}
        svg = _gen_qr_svg(QR_CONTENT.format(key=key))
        if not svg:
            return {"ok": False, "msg": "二维码生成失败"}
        return {"ok": True, "key": key, "svg": svg}

    def qr_poll(self, key: str) -> dict:
        meta = _qr_sessions.get(key)
        if not meta:
            return {"status": 800}
        session = meta["session"]
        try:
            data = encrypt({"key": key, "type": 1})
            r = session.post(
                "https://music.163.com/weapi/login/qrcode/client/login",
                data=data, timeout=15,
            )
            j = r.json()
        except Exception as e:
            return {"status": 0, "msg": str(e), "raw": f"请求异常: {e}"}

        code = j.get("code", 0)
        if code == 803:
            cookie = (j.get("cookie") or "").strip() or _extract_set_cookie(r)
            if cookie:
                self.on_success(cookie)
                _qr_sessions.pop(key, None)
                log.info("扫码登录成功，Cookie 已更新")
                return {"status": 803, "ok": True, "raw": j}
            return {"status": 803, "ok": False, "raw": j}
        msg = j.get("message", "")
        return {"status": code, "msg": msg, "raw": j}
