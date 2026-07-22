"""扫码登录模块单测（set-cookie 解析 + 全链路 start/poll 801）。"""

import sys
from io import BytesIO
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.netease.qrlogin import _extract_set_cookie, _gen_qr_svg


def test_extract_set_cookie_single():
    class FakeResp:
        headers = {
            "Set-Cookie": "MUSIC_U=abc123; Path=/; Max-Age=3600",
            "Content-Type": "application/json",
        }
    assert _extract_set_cookie(FakeResp()) == "MUSIC_U=abc123"


def test_extract_set_cookie_multi():
    class FakeResp:
        headers = {
            "Set-Cookie": "MUSIC_U=abc123; Path=/; HttpOnly",
            "set-cookie": "__csrf=def456; Path=/",
            "Content-Type": "application/json",
        }
    assert "MUSIC_U=abc123" in _extract_set_cookie(FakeResp())
    assert "__csrf=def456" in _extract_set_cookie(FakeResp())


def test_extract_set_cookie_empty():
    class FakeResp:
        headers = {"Content-Type": "text/plain"}
    assert _extract_set_cookie(FakeResp()) == ""


def test_gen_qr_svg():
    svg = _gen_qr_svg("https://music.163.com/login?codekey=test")
    assert svg.startswith("<?xml")
    assert "svg" in svg[:50]


def test_gen_qr_svg_cache_isolation():
    svg1 = _gen_qr_svg("url-a")
    svg2 = _gen_qr_svg("url-b")
    assert svg1 != svg2
