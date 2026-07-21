"""状态页：FastAPI 单页应用 + JSON API。"""

import json
import logging
import threading
import time

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse

log = logging.getLogger(__name__)

PAGE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Navidrome Sync 状态</title>
<style>
  :root { color-scheme: dark; }
  * { box-sizing: border-box; }
  body { font-family: -apple-system, "PingFang SC", "Microsoft YaHei", sans-serif;
         background: #0f1420; color: #dfe6f0; margin: 0; padding: 24px; }
  h1 { font-size: 20px; margin: 0 0 4px; }
  .sub { color: #7d8aa5; font-size: 13px; margin-bottom: 20px; }
  .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 16px; }
  .card { background: #171e2e; border: 1px solid #232c42; border-radius: 10px; padding: 16px; }
  .card h2 { font-size: 14px; margin: 0 0 12px; color: #8fb8ff; }
  .ok { color: #4ade80; } .bad { color: #f87171; } .warn { color: #fbbf24; }
  table { width: 100%; border-collapse: collapse; font-size: 13px; }
  th, td { text-align: left; padding: 6px 8px; border-bottom: 1px solid #232c42; }
  th { color: #7d8aa5; font-weight: normal; }
  button { background: #2563eb; color: #fff; border: 0; border-radius: 6px;
           padding: 8px 16px; cursor: pointer; font-size: 13px; }
  button:disabled { background: #334155; cursor: not-allowed; }
  .pill { display: inline-block; padding: 1px 8px; border-radius: 99px; font-size: 12px; }
  .pill.downloaded { background: #064e3b; color: #6ee7b7; }
  .pill.existed { background: #1e3a8a; color: #93c5fd; }
  .pill.failed, .pill.dead { background: #7f1d1d; color: #fca5a5; }
  .pill.pending { background: #3b3f4a; color: #cbd5e1; }
  .stat { font-size: 28px; font-weight: 600; }
  .stat-label { font-size: 12px; color: #7d8aa5; }
  .row { display: flex; gap: 24px; flex-wrap: wrap; }
  button.retry { padding: 2px 10px; font-size: 12px; background: #334155; }
</style>
</head>
<body>
<h1>🎵 Navidrome Sync</h1>
<div class="sub" id="next-run">加载中…</div>

<div class="grid">
  <div class="card">
    <h2>运行状态</h2>
    <div id="status"></div>
    <div style="margin-top:12px">
      <button id="run-btn" onclick="triggerRun()">立即运行每日任务</button>
    </div>
  </div>
  <div class="card">
    <h2>曲目统计</h2>
    <div class="row" id="stats"></div>
  </div>
  <div class="card">
    <h2>最近运行</h2>
    <table id="runs"></table>
  </div>
</div>

<div class="grid" style="margin-top:16px">
  <div class="card">
    <h2>最近入库</h2>
    <table id="downloaded"></table>
  </div>
  <div class="card">
    <h2>失败 / 重试队列</h2>
    <table id="failed"></table>
  </div>
</div>

<script>
const fmt = ts => ts ? new Date(ts*1000).toLocaleString('zh-CN', {hour12:false}) : '-';
const pill = s => `<span class="pill ${s}">${s}</span>`;

async function load() {
  const st = await (await fetch('/api/status')).json();
  document.getElementById('next-run').textContent =
    `下次运行：${st.next_run || '未知'}　|　上次运行：${fmt(st.last_run)}`;
  document.getElementById('status').innerHTML = `
    <div>网易云 Cookie：${st.cookie_ok === null ? '<span class="warn">未知</span>'
      : st.cookie_ok ? '<span class="ok">✓ 有效</span>' : '<span class="bad">✗ 失效/未配置</span>'}</div>
    <div>下载源链：${st.dl_sources.join(' → ')}</div>
    <div>推荐源：${st.enabled_sources.join('、') || '无'}</div>
    <div>正在运行：${st.running ? '<span class="warn">是</span>' : '否'}</div>`;
  const stats = await (await fetch('/api/stats')).json();
  document.getElementById('stats').innerHTML = Object.entries(stats).map(([k, v]) =>
    `<div><div class="stat">${v}</div><div class="stat-label">${k}</div></div>`).join('');

  const runs = await (await fetch('/api/runs')).json();
  document.getElementById('runs').innerHTML =
    '<tr><th>时间</th><th>结果</th></tr>' + runs.map(r =>
      `<tr><td>${fmt(r.started_at)}</td><td style="font-size:12px">${r.stats}</td></tr>`).join('');

  const dl = await (await fetch('/api/tracks?status=downloaded&limit=20')).json();
  document.getElementById('downloaded').innerHTML =
    '<tr><th>曲目</th><th>歌单</th><th>源</th></tr>' + dl.map(t =>
      `<tr><td>${t.artists.join('/')} - ${t.title}</td><td>${t.playlist || '-'}</td>
       <td>${t.download_source}</td></tr>`).join('');

  const failed = await (await fetch('/api/tracks?status=failed&limit=50')).json();
  const dead = await (await fetch('/api/tracks?status=dead&limit=50')).json();
  document.getElementById('failed').innerHTML =
    '<tr><th>曲目</th><th>原因</th><th>次数</th><th>下次重试</th><th></th></tr>' +
    failed.concat(dead).map(t =>
      `<tr><td>${t.artists.join('/')} - ${t.title}</td><td>${t.fail_reason}</td>
       <td>${t.attempts}</td><td>${fmt(t.next_retry_at)}</td>
       <td><button class="retry" onclick="retry(${t.id})">重试</button></td></tr>`).join('');
}

async function triggerRun() {
  const btn = document.getElementById('run-btn');
  btn.disabled = true; btn.textContent = '已触发，运行中…';
  await fetch('/api/run', {method: 'POST'});
  setTimeout(() => { btn.disabled = false; btn.textContent = '立即运行每日任务'; load(); }, 5000);
}

async function retry(id) {
  await fetch(`/api/retry/${id}`, {method: 'POST'});
  load();
}

load();
setInterval(load, 30000);
</script>
</body>
</html>
"""


def create_app(cfg, db, jobs, scheduler=None):
    app = FastAPI(title="navidrome-sync")

    @app.get("/", response_class=HTMLResponse)
    def index():
        return PAGE

    @app.get("/api/status")
    def status():
        next_run = None
        if scheduler:
            job = scheduler.get_job("daily_sync")
            if job and job.next_run_time:
                next_run = job.next_run_time.strftime("%Y-%m-%d %H:%M:%S")
        runs = db.list_runs(1)
        enabled = [n for n, sc in cfg.sources.items() if sc.enabled]
        return {
            "cookie_ok": jobs.last_cookie_ok,
            "dl_sources": cfg.dl_sources,
            "enabled_sources": enabled,
            "next_run": next_run,
            "last_run": runs[0]["started_at"] if runs else None,
            "running": jobs._lock.locked(),
        }

    @app.get("/api/stats")
    def stats():
        return db.stats()

    @app.get("/api/runs")
    def runs():
        return db.list_runs(10)

    @app.get("/api/tracks")
    def tracks(status: str = "", limit: int = 50):
        rows = db.list_tracks(status or None, limit)
        for r in rows:
            try:
                r["artists"] = json.loads(r["artists"])
            except Exception:
                r["artists"] = [r["artists"]]
        return rows

    @app.post("/api/run")
    def run_now():
        if jobs._lock.locked():
            return JSONResponse({"ok": False, "msg": "任务正在运行中"}, status_code=409)
        threading.Thread(target=jobs.daily_run, daemon=True).start()
        return {"ok": True}

    @app.post("/api/retry/{track_id}")
    def retry(track_id: int):
        db.reset_retry(track_id)
        return {"ok": True}

    return app
