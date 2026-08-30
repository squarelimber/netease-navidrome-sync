"""check_cookie 响应解析回归测试。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.api_client import NCMAPIClient


def _client_with(login_status_body: dict) -> NCMAPIClient:
    c = NCMAPIClient("http://mock")
    c.set_cookie("MUSIC_U=abc; __csrf=xyz")

    def fake_get(path, **params):
        assert path == "/login/status"
        return login_status_body

    c._get = fake_get
    return c


def test_check_cookie_api_enhanced_shape():
    """api-enhanced: 顶层无 code，code 在 data 内。"""
    c = _client_with({
        "data": {"code": 200, "account": {"id": 1}, "profile": {"nickname": "x"}},
    })
    assert c.check_cookie() is True


def test_check_cookie_top_level_code():
    """兼容顶层 code 的 fork。"""
    c = _client_with({
        "code": 200,
        "data": {"account": {"id": 1}},
    })
    assert c.check_cookie() is True


def test_check_cookie_not_logged_in():
    """未登录：顶层 code 301 无 data。"""
    c = _client_with({"code": 301})
    assert c.check_cookie() is False


def test_check_cookie_empty_cookie():
    c = NCMAPIClient("http://mock")
    assert c.check_cookie() is False


def test_check_cookie_state_distinguishes_network_error():
    c = _client_with({"code": -1, "_request_error": True})
    assert c.check_cookie_state() is None
    assert c.check_cookie() is False


def test_check_cookie_anonymous_account_is_not_logged_in():
    """ncm-api 自带匿名账号（anonimousUser=true、profile=null）必须判为未登录。

    这是 cookie 未生效/失效时的真实响应形状，旧逻辑因 account 非空而误报已登录。
    """
    c = _client_with({
        "data": {
            "code": 200,
            "account": {
                "id": 17866516234,
                "userName": "1000_5D57...",
                "type": 1000,
                "status": -10,
                "anonimousUser": True,
            },
            "profile": None,
        },
    })
    assert c.check_cookie() is False
    assert c.check_cookie_state() is False


def test_check_cookie_real_user_with_profile():
    """真实登录用户：有 profile、无 anonimousUser 标记。"""
    c = _client_with({
        "data": {
            "code": 200,
            "account": {"id": 999, "status": 200},
            "profile": {"userId": 999, "nickname": "real"},
        },
    })
    assert c.check_cookie() is True
