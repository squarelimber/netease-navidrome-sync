"""状态页：FastAPI 单页应用 + JSON API。"""

import json
import logging
import threading

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse

log = logging.getLogger(__name__)

PAGE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Navidrome Sync</title>
<style>
  :root { color-scheme: dark; --bg:#0b1020; --card:#141b2e; --line:#243049;
          --muted:#8b97b3; --accent:#5b8cff; --ok:#34d399; --bad:#f87171;
          --warn:#fbbf24; --blue:#60a5fa; --radius:12px; }
  * { box-sizing:border-box; }
  body { font-family:-apple-system,"PingFang SC","Microsoft YaHei",sans-serif;
         background:linear-gradient(180deg,#0b1020,#0a0f1d 60%); color:#e6edf6;
         margin:0; padding:28px 32px 60px; min-height:100vh; }
  h1 { font-size:22px; margin:0 0 2px; letter-spacing:.5px; }
  h1 span { color:var(--accent); }
  .sub { color:var(--muted); font-size:13px; margin-bottom:22px; }
  .grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(300px,1fr)); gap:16px; }
  .card { background:var(--card); border:1px solid var(--line); border-radius:var(--radius);
          padding:18px; box-shadow:0 6px 24px rgba(0,0,0,.25); }
  .card h2 { font-size:13px; margin:0 0 14px; color:#9bb6ff; font-weight:600;
             text-transform:uppercase; letter-spacing:.8px; }
  .row { display:flex; gap:10px; flex-wrap:wrap; }
  .kv { font-size:13px; line-height:1.9; color:#cdd6e6; }
  .kv b { color:#fff; font-weight:600; }
  .ok { color:var(--ok); } .bad { color:var(--bad); } .warn { color:var(--warn); }
  .stat { text-align:center; padding:6px 10px; min-width:78px; }
  .stat .n { font-size:26px; font-weight:700; line-height:1; }
  .stat .l { font-size:11px; color:var(--muted); margin-top:4px; }
  .n.ok { color:var(--ok); } .n.bad { color:var(--bad); }
  .n.blue { color:var(--blue); } .n.warn { color:var(--warn); }
  .scroll { max-height:380px; overflow:auto; border-radius:8px; }
  .scroll::-webkit-scrollbar { width:8px; height:8px; }
  .scroll::-webkit-scrollbar-thumb { background:#2a3650; border-radius:8px; }
  .scroll::-webkit-scrollbar-thumb:hover { background:#36466a; }
  table { width:100%; border-collapse:collapse; font-size:13px; }
  th,td { text-align:left; padding:7px 10px; border-bottom:1px solid var(--line); }
  th { color:var(--muted); font-weight:500; font-size:12px; position:sticky; top:0;
       background:var(--card); z-index:1; }
  tr:hover td { background:rgba(91,140,255,.06); }
  button { background:var(--accent); color:#fff; border:0; border-radius:8px;
           padding:9px 18px; cursor:pointer; font-size:13px; font-weight:500;
           transition:filter .15s,opacity .15s; }
  button:hover { filter:brightness(1.1); }
  button:disabled { background:#33415a; cursor:not-allowed; }
  button.secondary { background:#2a3650; }
  button.danger { background:#7f1d1d; }
  button.small { padding:3px 10px; font-size:12px; background:#2a3650; }
  .pill { display:inline-block; padding:1px 9px; border-radius:99px; font-size:11px;
          font-weight:600; margin-right:4px; }
  .pill.downloaded { background:#064e3b; color:#6ee7b7; }
  .pill.existed { background:#1e3a8a; color:#93c5fd; }
  .pill.failed { background:#7f1d1d; color:#fca5a5; }
  .pill.dead { background:#3b1d1d; color:#9a7a7a; }
  .pill.skipped { background:#3b3f4a; color:#cbd5e1; }
  .pill.retried { background:#78350f; color:#fcd34d; }
  .pill.src { background:#1e293b; color:#94a3b8; }
  .muted { color:var(--muted); }
  .run-stats { font-size:12px; }
  .bar { display:flex; gap:12px; margin-top:14px; align-items:center; flex-wrap:wrap; }
  #run-state { font-size:13px; color:var(--warn); }
  .qr-box { text-align:center; }
  .qr-box img, .qr-box svg { max-width:220px; border-radius:8px; background:#fff; padding:8px; }
  .qr-tip { font-size:12px; color:var(--muted); margin-top:8px; }
  .hide { display:none; }
  .input { background:#0f1a33; border:1px solid var(--line); border-radius:8px; padding:9px 12px;
           color:#fff; font-size:13px; width:100%; margin-bottom:8px; }
  .input::placeholder { color:#5a6a88; }
  .input-group { margin-bottom:6px; }
  .input-group label { display:block; font-size:12px; color:var(--muted); margin-bottom:3px; }
  .login-tab { display:flex; gap:0; margin-bottom:12px; }
  .login-tab button { flex:1; background:transparent; color:var(--muted); font-size:13px;
                      padding:8px; border-radius:0; border-bottom:2px solid transparent; }
  .login-tab button.active { color:#fff; border-bottom-color:var(--accent); }
</style>
</head>
<body>
<h1>🎵 <span>Navidrome Sync</span></h1>
<div class="sub" id="next-run">加载中…</div>

<div class="grid">
  <div class="card">
    <h2>运行状态</h2>
    <div class="kv" id="status"></div>
    <div class="bar">
      <button id="run-btn" onclick="triggerRun()">立即运行</button>
      <button id="stop-btn" class="danger hide" onclick="stopRun()">停止</button>
      <button id="refresh-btn" class="secondary" onclick="toggleRefresh(true)">暂停自动刷新</button>
      <span id="run-state"></span>
    </div>
  </div>

  <div class="card">
    <h2>曲目统计</h2>
    <div class="row" id="stats"></div>
  </div>

  <div class="card" id="login-card">
    <h2>网易云登录</h2>
    <div class="login-tab">
      <button id="tab-phone" class="active" onclick="switchLoginTab('phone')">手机号登录</button>
      <button id="tab-qr" onclick="switchLoginTab('qr')">扫码登录(备用)</button>
    </div>
    <div id="login-phone">
      <div class="input-group"><label>手机号</label><input id="login-phone-input" class="input" placeholder="13800138000" type="tel"></div>
      <div class="input-group"><label>密码</label><input id="login-pwd-input" class="input" placeholder="" type="password" onkeydown="if(event.key==='Enter')phoneLogin()"></div>
      <button onclick="phoneLogin()" style="width:100%">登录</button>
      <div id="login-phone-status" class="qr-tip"></div>
    </div>
    <div id="login-qr" class="hide qr-box">
      <button onclick="qrStart()">显示二维码</button>
      <div id="qr-img"></div>
      <div class="qr-tip" id="qr-tip">扫码接口可能已被封锁</div>
      <div id="qr-debug" class="muted" style="font-size:11px;margin-top:4px;word-break:break-all"></div>
    </div>
  </div>
</div>

<div class="grid" style="margin-top:16px">
  <div class="card">
    <h2>最近运行</h2>
    <div class="scroll"><table id="runs"></table></div>
  </div>
  <div class="card">
    <h2>最近入库 <span class="muted" style="font-weight:400;text-transform:none">(可滚动)</span></h2>
    <div class="scroll"><table id="downloaded"></table></div>
  </div>
  <div class="card">
    <h2>失败 / 重试队列 <span class="muted" style="font-weight:400;text-transform:none">(可滚动)</span></h2>
    <div class="scroll"><table id="failed"></table></div>
  </div>
</div>

<script>
const fmt = ts => ts ? new Date(ts*1000).toLocaleString('zh-CN',{hour12:false}) : '-';
let autoRefresh = true, qrTimer = null;

function pills(s) {
  return `<span class="pill ${s}">${({downloaded:'已下',existed:'已有',skipped:'跳过',failed:'失败',dead:'放弃',pending:'待处理'})[s]||s}</span>`;
}
function statBox(n, label, cls='') {
  return `<div class="stat"><div class="n ${cls}">${n}</div><div class="l">${label}</div></div>`;
}
function runSummary(stats) {
  let s = stats || {};
  let html = '';
  for (const k of ['downloaded','existed','skipped','failed','retried']) {
    if (s[k]) html += `<span class="pill ${k}">${({downloaded:'已下',existed:'已有',skipped:'跳过',failed:'失败',retried:'重试'})[k]} ${s[k]}</span>`;
  }
  if (s.duration_s) html += `<span class="muted"> ${s.duration_s}s</span>`;
  if (s.cookie_ok === false) html += `<span class="pill failed">Cookie失效</span>`;
  if (s.aborted) html += `<span class="pill retried">已中止</span>`;
  if (s.error) html += `<span class="pill failed">错误</span>`;
  return html || '<span class="muted">无数据</span>';
}

async function load() {
  if (!autoRefresh) return;
  const st = await (await fetch('/api/status')).json();
  document.getElementById('next-run').textContent =
    `下次运行：${st.next_run || '未知'}　·　上次运行：${fmt(st.last_run)}`;
  const ck = st.cookie_ok;
  const ckHtml = ck === null ? '<span class="warn">未知</span>'
    : ck ? '<span class="ok">✓ 有效</span>' : '<span class="bad">✗ 失效/未配置</span>';
  document.getElementById('status').innerHTML = `
    <div>网易云 Cookie：${ckHtml}</div>
    <div>下载源链：<b>${st.dl_sources.join(' → ')}</b></div>
    <div>推荐源：<b>${st.enabled_sources.join('、') || '无'}</b></div>
    <div>正在运行：<b>${st.running ? '<span class="warn">是</span>' : '否'}</b></div>`;
  document.getElementById('run-btn').disabled = st.running;
  document.getElementById('stop-btn').classList.toggle('hide', !st.running);
  document.getElementById('run-state').textContent = st.running ? '任务运行中…' : '';

  const stats = await (await fetch('/api/stats')).json();
  document.getElementById('stats').innerHTML =
    statBox(stats.downloaded||0,'已下载','ok') +
    statBox(stats.existed||0,'已存在','blue') +
    statBox(stats.failed||0,'失败','bad') +
    statBox(stats.dead||0,'放弃','bad') +
    statBox(stats.pending||0,'待处理','warn');

  const runs = await (await fetch('/api/runs')).json();
  document.getElementById('runs').innerHTML =
    '<tr><th>时间</th><th>结果</th></tr>' + runs.map(r =>
      `<tr><td class="muted">${fmt(r.started_at)}</td>
       <td class="run-stats">${runSummary(typeof r.stats==='string'?JSON.parse(r.stats||'{}'):r.stats)}</td></tr>`).join('');

  const dl = await (await fetch('/api/tracks?status=downloaded&limit=200')).json();
  document.getElementById('downloaded').innerHTML =
    '<tr><th>曲目</th><th>歌单</th><th>源</th></tr>' + dl.map(t =>
      `<tr><td>${t.artists.join('/')} - ${t.title}</td><td class="muted">${t.playlist||'-'}</td>
       <td><span class="pill src">${t.download_source}</span></td></tr>`).join('');

  const failed = await (await fetch('/api/tracks?status=failed&limit=200')).json();
  const dead = await (await fetch('/api/tracks?status=dead&limit=50')).json();
  document.getElementById('failed').innerHTML =
    '<tr><th>曲目</th><th>原因</th><th>次</th><th>下次重试</th><th></th></tr>' +
    failed.concat(dead).map(t =>
      `<tr><td>${t.artists.join('/')} - ${t.title}</td>
       <td class="muted">${t.fail_reason}</td><td>${t.attempts}</td>
       <td class="muted">${fmt(t.next_retry_at)}</td>
       <td><button class="small" onclick="retry(${t.id})">重试</button></td></tr>`).join('');
}

async function triggerRun() {
  if (!confirm('立即执行每日任务？')) return;
  const btn = document.getElementById('run-btn');
  btn.disabled = true; btn.textContent = '运行中…';
  await fetch('/api/run', {method:'POST'});
  setTimeout(load, 1500);
}
async function stopRun() {
  await fetch('/api/stop', {method:'POST'});
  document.getElementById('run-state').textContent = '已请求中止…';
  setTimeout(load, 2000);
}
function toggleRefresh(toState) {
  autoRefresh = !autoRefresh;
  const btn = document.getElementById('refresh-btn');
  btn.textContent = autoRefresh ? '暂停自动刷新' : '恢复自动刷新';
  btn.classList.toggle('secondary', autoRefresh);
  if (autoRefresh) load();
}
async function retry(id) {
  await fetch(`/api/retry/${id}`, {method:'POST'});
  load();
}
async function qrStart() {
  document.getElementById('qr-tip').textContent = '生成二维码…';
  const r = await (await fetch('/api/qr/start')).json();
  if (!r.ok) { document.getElementById('qr-tip').innerHTML = '<span class="bad">'+r.msg+'</span>'; return; }
  document.getElementById('qr-img').innerHTML = r.svg;
  document.getElementById('qr-tip').innerHTML = '请用 <b>网易云音乐 App</b> 扫码<br><small class="muted">如提示升级版本，请改用手机号登录</small>';
  if (qrTimer) clearInterval(qrTimer);
  qrTimer = setInterval(() => qrPoll(r.key), 2000);
}
async function qrPoll(key) {
  const r = await (await fetch('/api/qr/poll?key='+encodeURIComponent(key))).json();
  const tip = document.getElementById('qr-tip');
  const debug = document.getElementById('qr-debug');
  if (r.raw) debug.textContent = '回应: ' + JSON.stringify(r.raw);
  else debug.textContent = '';
  if (r.status === 801) tip.innerHTML = '等待扫码…';
  else if (r.status === 802) tip.innerHTML = '<span class="warn">已扫码，请在手机确认登录</span>';
  else if (r.status === 803) {
    tip.innerHTML = '<span class="ok">✓ 登录成功，Cookie 已更新</span>';
    clearInterval(qrTimer); qrTimer = null; load();
  } else if (r.status === 800) {
    tip.innerHTML = '<span class="bad">二维码已过期，请重新生成</span>';
    clearInterval(qrTimer); qrTimer = null;
  } else {
    tip.innerHTML = '<span class="bad">扫码不可用 ('+r.status+')</span>';
  }
}
function switchLoginTab(tab) {
  document.getElementById('login-phone').classList.toggle('hide', tab !== 'phone');
  document.getElementById('login-qr').classList.toggle('hide', tab !== 'qr');
  document.getElementById('tab-phone').classList.toggle('active', tab === 'phone');
  document.getElementById('tab-qr').classList.toggle('active', tab === 'qr');
}
async function phoneLogin() {
  const phone = document.getElementById('login-phone-input').value.trim();
  const pwd = document.getElementById('login-pwd-input').value;
  const status = document.getElementById('login-phone-status');
  if (!phone || !pwd) { status.innerHTML = '<span class="bad">请输入手机号和密码</span>'; return; }
  status.innerHTML = '登录中…';
  const r = await (await fetch('/api/login/phone', {method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({phone, password: pwd})})).json();
  status.innerHTML = r.ok
    ? '<span class="ok">✓ 登录成功，Cookie 已更新</span>'
    : '<span class="bad">✗ ' + (r.msg || '登录失败') + '</span>';
  if (r.ok) { document.getElementById('login-phone-input').value = ''; document.getElementById('login-pwd-input').value = ''; load(); }
  if (r.raw) status.innerHTML += '<div class="muted" style="font-size:11px">' + JSON.stringify(r.raw).substring(0,200) + '</div>';
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
        last_stats = {}
        if runs and runs[0].get("stats"):
            try:
                last_stats = json.loads(runs[0]["stats"]) if isinstance(runs[0]["stats"], str) else runs[0]["stats"]
            except Exception:
                last_stats = {}
        return {
            "cookie_ok": jobs.last_cookie_ok,
            "dl_sources": cfg.dl_sources,
            "enabled_sources": enabled,
            "next_run": next_run,
            "last_run": runs[0]["started_at"] if runs else None,
            "running": jobs._lock.locked(),
            "aborted": jobs.aborted,
            "last_aborted": bool(last_stats.get("aborted")),
        }

    @app.get("/api/stats")
    def stats():
        return db.stats()

    @app.get("/api/runs")
    def runs():
        return db.list_runs(10)

    @app.get("/api/tracks")
    def tracks(status: str = "", limit: int = 200):
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

    @app.post("/api/stop")
    def stop_run():
        if not jobs._lock.locked():
            return JSONResponse({"ok": False, "msg": "当前没有运行中的任务"}, status_code=409)
        jobs.stop()
        return {"ok": True}

    @app.post("/api/retry/{track_id}")
    def retry(track_id: int):
        db.reset_retry(track_id)
        return {"ok": True}

    # 网易云登录端点（由 LoginHandler 注入）
    @app.get("/api/qr/start")
    def qr_start():
        handler = getattr(app.state, "qr_handler", None)
        if not handler:
            return {"ok": False, "msg": "登录模块未初始化"}
        return handler.qr_start()

    @app.get("/api/qr/poll")
    def qr_poll(key: str):
        handler = getattr(app.state, "qr_handler", None)
        if not handler:
            return {"ok": False, "status": 0}
        return handler.qr_poll(key)

    @app.post("/api/login/phone")
    async def phone_login(req: Request):
        handler = getattr(app.state, "qr_handler", None)
        if not handler:
            return {"ok": False, "msg": "登录模块未初始化"}
        body = await req.json()
        return handler.phone_login(str(body.get("phone", "")), str(body.get("password", "")))

    return app
