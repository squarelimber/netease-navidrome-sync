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
