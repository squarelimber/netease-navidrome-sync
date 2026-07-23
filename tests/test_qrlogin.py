"""登录模块测试（扫码 + 手机号）。"""

import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.netease.qrlogin import _gen_qr_svg


def test_gen_qr_svg():
    svg = _gen_qr_svg("https://music.163.com/login?codekey=test")
    assert svg.startswith("<?xml")
    assert "svg" in svg


def test_gen_qr_svg_cache_isolation():
    svg1 = _gen_qr_svg("url-a")
    svg2 = _gen_qr_svg("url-b")
    assert svg1 != svg2


def test_mock_phone_login():
    """手机号登录 mock（零网络）。"""
    captured = []

    def on_ok(c):
        captured.append(c)

    class FakeAPI:
        def login_cellphone(self, phone, password):
            return {"ok": True, "cookie": "MUSIC_U=f_u; __csrf=f_csrf"}

    from app.netease.qrlogin import LoginHandler
    h = LoginHandler(FakeAPI(), on_ok)
    r = h.phone_login("13800000000", "pwd")
    assert r["ok"], r
    assert "MUSIC_U=f_u" in captured[0]
    assert "__csrf=f_csrf" in captured[0]


def test_mock_qr_login():
    """扫码登录 mock（零网络）。"""
    captured = []

    def on_ok(c):
        captured.append(c)

    class FakeAPI:
        def __init__(self):
            self.call = 0

        def login_qr_key(self):
            return {"ok": True, "key": "mock-key", "qrurl": "https://music.163.com/login?codekey=mock-key"}

        def login_qr_check(self, key):
            self.call += 1
            if self.call < 3:
                return {"status": 801}
            return {"status": 803, "cookie": "MUSIC_U=f_u; __csrf=f_csrf"}

    from app.netease.qrlogin import LoginHandler
    h = LoginHandler(FakeAPI(), on_ok)
    r = h.qr_start()
    assert r["ok"] and r["key"] == "mock-key"
    assert r["svg"].startswith("<?xml")
    assert h.qr_poll("mock-key")["status"] == 801
    assert h.qr_poll("mock-key")["status"] == 801
    p = h.qr_poll("mock-key")
    assert p["status"] == 803 and p.get("ok") is True
    assert "MUSIC_U=f_u" in captured[0]
