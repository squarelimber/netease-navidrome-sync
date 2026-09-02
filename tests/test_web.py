"""状态页 API 端点测试（FastAPI TestClient）。"""

import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient  # noqa: E402

from app.db import SCROBBLE_TS_KEY  # noqa: E402
from app.web import create_app  # noqa: E402


class _FakeDB:
    def __init__(self, props=None):
        self.props = dict(props or {})

    def get_property(self, key, default=""):
        return self.props.get(key, default)

    def set_property(self, key, value):
        self.props[key] = value


class _FakeJobs:
    def __init__(self):
        self._lock = threading.Lock()
        self.last_manual_scrobble = None
        self.aborted = False
        self.youtube_cookie_status = {"state": "unchecked"}
        self.last_cookie_ok = True
        self.last_cookie_check_at = 0.0

    def refresh_cookie_status(self):
        self.last_cookie_ok = True


class _FakeCfg:
    web_auth_user = ""
    web_auth_password = ""
    dl_sources = ["ytdlp"]
    title_threshold = 85
    max_duration_diff = 12

    def __init__(self):
        self.sources = {}


def _client(db, jobs):
    return TestClient(create_app(_FakeCfg(), db, jobs))


def test_reset_watermark_sets_zero():
    db = _FakeDB({SCROBBLE_TS_KEY: "1788091147"})
    jobs = _FakeJobs()
    c = _client(db, jobs)
    r = c.post("/api/scrobble/reset-watermark")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["prev"] == "1788091147"
    # 水位被重置为 0
    assert db.get_property(SCROBBLE_TS_KEY) == "0"


def test_reset_watermark_when_absent():
    db = _FakeDB({})
    jobs = _FakeJobs()
    c = _client(db, jobs)
    r = c.post("/api/scrobble/reset-watermark")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["prev"] == "0"
    assert db.get_property(SCROBBLE_TS_KEY) == "0"


def test_reset_watermark_rejects_when_running():
    db = _FakeDB({SCROBBLE_TS_KEY: "1788091147"})
    jobs = _FakeJobs()
    # 模拟任务正在运行（锁被持有）
    jobs._lock.acquire()
    try:
        c = _client(db, jobs)
        r = c.post("/api/scrobble/reset-watermark")
        assert r.status_code == 409
        assert r.json()["ok"] is False
        # 水位未被改动
        assert db.get_property(SCROBBLE_TS_KEY) == "1788091147"
    finally:
        jobs._lock.release()


# ---- _scrobble_status 显示：新 / 已打卡 / 失败 三段 ----

def test_scrobble_status_ok_with_skipped():
    from app.web import _scrobble_status
    html = _scrobble_status({"ok": True, "count": 8, "fail": 0, "skipped": 187, "total": 200})
    assert "新 8 首" in html and "已打卡 187" in html
    assert "✗" not in html  # 无失败不应显示失败标记


def test_scrobble_status_ok_no_skipped():
    from app.web import _scrobble_status
    html = _scrobble_status({"ok": True, "count": 8, "fail": 0, "skipped": 0, "total": 8})
    assert "✓ 8 首" in html
    assert "已打卡" not in html


def test_scrobble_status_with_failures_shows_breakdown():
    from app.web import _scrobble_status
    # 对应日志：8 新 + 187 已打卡 + 5 失败 = 200
    html = _scrobble_status({"ok": False, "count": 8, "fail": 5, "skipped": 187, "total": 200})
    assert "新 8" in html and "已打卡 187" in html and "失败 5" in html
    assert "✗" in html
    # 不应再出现误导性的 '8/200 成功'
    assert "8/200" not in html


def test_scrobble_status_msg_only():
    from app.web import _scrobble_status
    html = _scrobble_status({"ok": False, "msg": "网易云 Cookie 无效"})
    assert "Cookie 无效" in html and "✗" in html


def test_scrobble_status_empty():
    from app.web import _scrobble_status
    assert _scrobble_status({}) == ""
    assert _scrobble_status(None) == ""
