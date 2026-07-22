"""网易云手机扫码登录。

流程：
1. weapi 申请 unikey（通过持久 Session，让服务端建立临时追踪）
2. 生成二维码 SVG（扫码内容：https://music.163.com/login?codekey=<unikey>）
3. 轮询 /weapi/login/qrcode/client/login（复用同一 Session）
   - 800 过期 / 801 等待扫码 / 802 已扫码待确认 / 803 确认登录
4. 803 返回时先从 JSON 响应体取 cookie 字段，再回退到 Set-Cookie 头
5. 通过 on_success 回调热更新 Jobs 的 NCMApi 并持久化
"""

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


class QRLoginHandler:
    def __init__(self, on_success: Callable[[str], None]):
        self.on_success = on_success

    def start(self) -> dict:
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
            return {"ok": False, "msg": "二维码生成失败（缺少 qrcode 库？）"}
        return {"ok": True, "key": key, "svg": svg}

    def poll(self, key: str) -> dict:
        meta = _qr_sessions.get(key)
        if not meta:
            return {"status": 800}
        session = meta["session"]
        try:
            data = encrypt({"key": key, "type": 1})
            r = session.post(
                "https://music.163.com/weapi/login/qrcode/client/login",
                data=data,
                headers={"Referer": "https://music.163.com/"},
                timeout=15,
            )
            j = r.json()
        except Exception as e:
            return {"status": 0, "msg": str(e), "raw": f"请求异常: {e}"}

        code = j.get("code", 0)

        if code == 803:
            # 优先从 JSON 体取 cookie（非加密接口走 Set-Cookie 头，weapi 接口可能在 body 里）
            cookie = (j.get("cookie") or "").strip()
            # 回退：从 Set-Cookie 响应头取
            if not cookie:
                cookie = _extract_set_cookie(r)
            if cookie:
                self.on_success(cookie)
                _qr_sessions.pop(key, None)
                log.info("扫码登录成功，Cookie 已更新（%d bytes）", len(cookie))
            else:
                log.warning("扫码登录 803 但未收到 Cookie，raw=%s", j)
            return {
                "status": 803,
                "ok": bool(cookie),
                "raw": {"code": 803, "got_cookie": bool(cookie)},
            }

        result = {"status": code}
        msg = j.get("message")
        if msg:
            result["msg"] = msg
        result["raw"] = j
        return result
