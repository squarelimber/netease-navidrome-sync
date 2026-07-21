"""网易云手机扫码登录。

流程：
1. weapi 申请 unikey
2. 生成二维码 SVG（扫码内容：https://music.163.com/login?codekey=<unikey>）
3. 轮询 /weapi/login/qrcode/client/login
   - 800 过期 / 801 等待扫码 / 802 已扫码待确认 / 803 确认登录（返回 Set-Cookie）
4. 成功后把 Cookie 写入 data/cookie.txt 并热更新 Jobs 的 NCMApi
"""

import logging
import time
from typing import Callable

import requests

from .weapi import encrypt

log = logging.getLogger(__name__)

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
QR_CONTENT = "https://music.163.com/login?codekey={key}"
_qr_sessions = {}  # key -> (unikey, created_at)


def _gen_qr_svg(text: str) -> str:
    """生成二维码 SVG 矢量图（无需 Pillow）。"""
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


class QRLoginHandler:
    def __init__(self, on_success: Callable[[str], None]):
        self.on_success = on_success

    def start(self) -> dict:
        try:
            data = encrypt({"noCookie": True, "type": 1})
            r = requests.post(
                "https://music.163.com/weapi/login/qrcode/unikey",
                data=data, headers={"User-Agent": UA, "Referer": "https://music.163.com"},
                timeout=15,
            )
            j = r.json()
            if j.get("code") != 200 or not j.get("unikey"):
                return {"ok": False, "msg": f"获取 unikey 失败: {j}"}
            key = j["unikey"]
        except Exception as e:
            return {"ok": False, "msg": f"请求失败: {e}"}
        _qr_sessions[key] = (key, time.time())
        svg = _gen_qr_svg(QR_CONTENT.format(key=key))
        if not svg:
            return {"ok": False, "msg": "二维码生成失败（缺少 qrcode 库？）"}
        return {"ok": True, "key": key, "svg": svg}

    def poll(self, key: str) -> dict:
        sess = _qr_sessions.get(key)
        if not sess:
            return {"status": 800}
        try:
            data = encrypt({"key": key, "type": 1})
            r = requests.post(
                "https://music.163.com/weapi/login/qrcode/client/login",
                data=data, headers={"User-Agent": UA, "Referer": "https://music.163.com"},
                timeout=15,
            )
            j = r.json()
        except Exception as e:
            return {"status": 0, "msg": str(e)}
        code = j.get("code", 0)
        if code == 803:
            # 成功登录：从响应头抓取 Set-Cookie 拼成 cookie 串
            cookie = "; ".join(
                f"{k}={v.split(';')[0].split('=', 1)[1]}"
                for k, v in r.headers.items() if k.lower() == "set-cookie" and "=" in v.split(';')[0]
            )
            if cookie:
                self.on_success(cookie)
                _qr_sessions.pop(key, None)
            return {"status": 803, "ok": bool(cookie)}
        if code in (800, 801, 802):
            return {"status": code}
        return {"status": code, "msg": j.get("message", "")}