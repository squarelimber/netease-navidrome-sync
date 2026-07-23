"""登录模块测试（扫码 + 手机号）。"""

import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.netease.qrlogin import _extract_set_cookie, _gen_qr_svg


class FakeResp:
    def __init__(self, headers):
        self.headers = headers


def test_extract_set_cookie_single():
    r = FakeResp({"Set-Cookie": "MUSIC_U=abc123; Path=/; Max-Age=3600"})
    assert _extract_set_cookie(r) == "MUSIC_U=abc123"


def test_extract_set_cookie_multi():
    r = FakeResp({
        "Set-Cookie": "MUSIC_U=abc123; Path=/; HttpOnly",
        "set-cookie": "__csrf=def456; Path=/",
    })
    out = _extract_set_cookie(r)
    assert "MUSIC_U=abc123" in out
    assert "__csrf=def456" in out


def test_extract_set_cookie_empty():
    assert _extract_set_cookie(FakeResp({})) == ""


def test_gen_qr_svg():
    svg = _gen_qr_svg("https://music.163.com/login?codekey=test")
    assert svg.startswith("<?xml")
    assert "svg" in svg


def test_gen_qr_svg_cache_isolation():
    svg1 = _gen_qr_svg("url-a")
    svg2 = _gen_qr_svg("url-b")
    assert svg1 != svg2


# ======== Mock 测试（零网络） ========

def _mock_resp(body: dict, headers: dict = None):
    m = MagicMock()
    m.json.return_value = body
    m.headers = headers or {}
    return m


def test_mock_qr_full_flow():
    seq = iter([
        _mock_resp({"code": 200, "unikey": "mk"}),
        _mock_resp({"code": 801}),
        _mock_resp({"code": 802}),
        _mock_resp({"code": 803, "cookie": "MUSIC_U=f_u; __csrf=f_csrf"}),
    ])
    captured = []
    def on_ok(c): captured.append(c)
    with patch("requests.Session.post", side_effect=seq):
        from app.netease.qrlogin import LoginHandler
        h = LoginHandler(on_ok)
        r = h.qr_start()
        assert r["ok"] and r["key"] == "mk"
        assert h.qr_poll(r["key"])["status"] == 801
        assert h.qr_poll(r["key"])["status"] == 802
        p = h.qr_poll(r["key"])
        assert p["status"] == 803 and p["ok"] is True
        assert "MUSIC_U=f_u" in captured[0]


def test_mock_phone_login():
    """手机号登录。"""
    ok_cb = object()

    def mock_post(url, data=None, **kw):
        m = MagicMock()
        if "/login/cellphone" in url:
            m.json.return_value = {"code": 200, "profile": {"nickname": "Tester"},
                                    "cookie": "MUSIC_U=test_u; __csrf=test_csrf"}
        else:
            m.json.return_value = {"code": 400}
        m.headers = {"Set-Cookie": "MUSIC_U=test_u; Path=/"}
        return m

    captured = []

    def on_ok(c):
        captured.append(c)

    with patch("requests.Session.post", side_effect=mock_post):
        from app.netease.qrlogin import LoginHandler
        h = LoginHandler(on_ok)
        r = h.phone_login("13800000000", "testpassword")
        assert r["ok"], r
        assert captured[0] == "MUSIC_U=test_u; __csrf=test_csrf"
        assert r["msg"] == "登录成功"
