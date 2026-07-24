"""扫码登录模块测试。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def test_mock_qr_login():
    """扫码登录 mock（零网络）。"""
    captured = []
    call_log = {"qr_key": 0, "qr_create": 0, "qr_check": 0}

    def on_ok(c):
        captured.append(c)

    class FakeAPI:
        def login_qr_key(self):
            call_log["qr_key"] += 1
            return {"ok": True, "key": "mock-key"}

        def login_qr_create(self, key, platform="web", qrimg=True):
            call_log["qr_create"] += 1
            return {"ok": True, "qrimg": "data:image/png;base64,fake", "qrurl": "https://example.com"}

        def login_qr_check(self, key):
            call_log["qr_check"] += 1
            n = call_log["qr_check"]
            if n < 3:
                return {"status": 801}
            return {"status": 803, "cookie": "MUSIC_U=f_u; __csrf=f_csrf"}

    from app.netease.qrlogin import LoginHandler
    h = LoginHandler(FakeAPI(), on_ok)
    r = h.qr_start()
    assert r["ok"] and r["key"] == "mock-key"
    assert r["qrimg"] == "data:image/png;base64,fake"
    assert call_log["qr_create"] == 1
    for expected in (801, 801, 803):
        p = h.qr_poll("mock-key")
        assert p["status"] == expected
        if expected == 803:
            assert p["ok"]
    assert "MUSIC_U=f_u" in captured[0]
