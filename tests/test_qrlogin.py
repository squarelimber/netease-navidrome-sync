"""扫码登录模块测试。

- 单元测试：set-cookie 解析、SVG 生成
- Mock 测试：模拟 801→802→803+Cookie 离线全流程
"""

import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.netease.qrlogin import _extract_set_cookie, _gen_qr_svg, _qr_sessions

# ======== 单元测试 ========

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


# ======== Mock 测试（零网络依赖） ========

def _mock_response(json_body: dict, headers: dict = None):
    m = MagicMock()
    m.json.return_value = json_body
    m.headers = headers or {}
    return m


def test_mock_qr_login_full_flow():
    """完整模拟 801→802→803+Cookie 流程，验证回调触发和 session 清理。"""
    seq = iter([
        _mock_response({"code": 200, "unikey": "mock-key-xxx"}),
        _mock_response({"code": 801, "message": "等待扫码"}),
        _mock_response({"code": 802, "message": "已扫码"}),
        _mock_response({"code": 803, "cookie": "MUSIC_U=fake_u; __csrf=fake_csrf"}),
    ])
    captured = []

    def on_ok(cookie):
        captured.append(cookie)

    with patch("requests.Session.post", side_effect=seq):
        from app.netease.qrlogin import QRLoginHandler
        handler = QRLoginHandler(on_ok)
        # start：需要一个 session 存放记录
        r = handler.start()
        assert r["ok"], r.get("msg")
        assert r["key"] == "mock-key-xxx"
        assert r["svg"].startswith("<?xml")
        # start 已完成 session 存储，无需手动插入
        # 三轮轮询
        for expected in (801, 802):
            assert handler.poll(r["key"])["status"] == expected
        p = handler.poll(r["key"])
        assert p["status"] == 803
        assert p["ok"] is True
        assert "MUSIC_U=fake_u" in captured[0]
        assert "__csrf=fake_csrf" in captured[0]
        # 确认 session 已被清理
        assert r["key"] not in _qr_sessions
    _qr_sessions.clear()


def test_mock_qr_login_no_cookie_on_803():
    """803 但无 Cookie，应返回 ok=False。"""
    seq = iter([
        _mock_response({"code": 200, "unikey": "mock-no-cookie"}),
        _mock_response({"code": 803}),
    ])
    with patch("requests.Session.post", side_effect=seq):
        from app.netease.qrlogin import QRLoginHandler
        handler = QRLoginHandler(lambda c: None)
        r = handler.start()
        assert r["ok"]
        p = handler.poll(r["key"])
        assert p["status"] == 803
        assert p["ok"] is False
    _qr_sessions.clear()
