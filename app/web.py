"""状态页：FastAPI 单页应用 + JSON API。"""

from __future__ import annotations

import base64
import hmac
import json
import logging
import threading
import time

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse

log = logging.getLogger(__name__)


def _scrobble_status(last_stats: dict) -> str:
    s = last_stats.get("scrobble", {})
    if not s:
        return ""
    if s.get("ok"):
        c = s.get("count", 0)
        return f'<span class="ok">✓ {c} 首</span>' if c else '<span class="muted">0 首</span>'
    return '<span class="warn">✗ ' + (s.get("msg", "?") or "?")[:30] + '</span>'


PAGE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Navidrome Sync</title>
<style>
  :root { color-scheme: dark;
    --bg:#0a0d17; --panel:rgba(255,255,255,.04); --line:rgba(255,255,255,.08);
    --txt:#e8edf6; --muted:#8a94ad;
    --accent:#6d8dff; --accent2:#9a6bff;
    --ok:#3ddc97; --bad:#ff6b6b; --warn:#ffc24b; --info:#5ad1ff;
    --r:16px; }
  * { box-sizing:border-box; }
  body { margin:0; min-height:100vh; color:var(--txt);
    font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","HarmonyOS Sans SC","Microsoft YaHei",sans-serif;
    background:
      radial-gradient(1100px 520px at 85% -10%, rgba(109,141,255,.16), transparent 60%),
      radial-gradient(900px 480px at -15% 25%, rgba(154,107,255,.12), transparent 55%),
      var(--bg);
    background-attachment:fixed; }
  ::-webkit-scrollbar { width:8px; height:8px; }
  ::-webkit-scrollbar-thumb { background:rgba(148,163,200,.18); border-radius:8px; }
  ::-webkit-scrollbar-thumb:hover { background:rgba(148,163,200,.32); }
  .hide { display:none !important; }
  .muted { color:var(--muted); }
  .ok { color:var(--ok); } .bad { color:var(--bad); } .warn { color:var(--warn); }

  /* ---------- 顶栏 ---------- */
  .topbar { position:sticky; top:0; z-index:50; display:flex; align-items:center;
    justify-content:space-between; gap:12px; padding:13px 28px;
    background:rgba(10,13,23,.75); backdrop-filter:blur(16px); -webkit-backdrop-filter:blur(16px);
    border-bottom:1px solid var(--line); }
  .brand { display:flex; align-items:center; gap:12px; }
  .logo { width:40px; height:40px; border-radius:12px; flex:0 0 auto;
    background:linear-gradient(135deg,var(--accent),var(--accent2)); color:#fff;
    display:flex; align-items:center; justify-content:center; font-size:19px;
    box-shadow:0 6px 18px rgba(109,141,255,.35); }
  .brand-name { font-size:15.5px; font-weight:700; letter-spacing:.3px; line-height:1.2; }
  .brand-name span { background:linear-gradient(90deg,var(--accent),var(--accent2));
    -webkit-background-clip:text; background-clip:text; color:transparent; }
  .brand-sub { font-size:11px; color:var(--muted); margin-top:2px; }
  .topbar-right { display:flex; align-items:center; gap:10px; }

  /* ---------- 布局 ---------- */
  main { max-width:1180px; margin:0 auto; padding:26px 28px 8px;
    display:flex; flex-direction:column; gap:18px; }
  .grid-two { display:grid; grid-template-columns:1.35fr 1fr; gap:18px; }
  .grid-three { display:grid; grid-template-columns:repeat(3,1fr); gap:18px; }
  @media (max-width:920px) { .grid-two,.grid-three { grid-template-columns:1fr; } }
  .footer { text-align:center; color:#5a6480; font-size:12px; padding:26px 0 12px; }

  /* ---------- 卡片 ---------- */
  .card { background:var(--panel); border:1px solid var(--line); border-radius:var(--r);
    padding:20px 22px; backdrop-filter:blur(6px); -webkit-backdrop-filter:blur(6px);
    box-shadow:0 12px 32px rgba(0,0,0,.28); animation:fadeUp .4s ease both; }
  @keyframes fadeUp { from { opacity:0; transform:translateY(8px); } to { opacity:1; transform:none; } }
  .card-head { display:flex; align-items:center; justify-content:space-between; gap:10px; margin-bottom:14px; }
  .card-head h2 { font-size:12.5px; font-weight:600; color:#a9b8e0; letter-spacing:.7px;
    text-transform:uppercase; margin:0; }
  .card-tip { font-size:11.5px; color:var(--muted); }

  /* ---------- 按钮 ---------- */
  .btn { display:inline-flex; align-items:center; gap:6px; border:0; cursor:pointer;
    background:linear-gradient(135deg,var(--accent),var(--accent2)); color:#fff;
    border-radius:10px; padding:9px 16px; font-size:13px; font-weight:600;
    transition:all .18s ease; box-shadow:0 6px 18px rgba(109,141,255,.25); }
  .btn:hover { transform:translateY(-1px); filter:brightness(1.07); box-shadow:0 10px 26px rgba(109,141,255,.38); }
  .btn:active { transform:none; }
  .btn:disabled { opacity:.45; cursor:not-allowed; transform:none; filter:grayscale(.4); }
  .btn.ghost { background:rgba(255,255,255,.05); border:1px solid var(--line);
    box-shadow:none; color:#c6d0e4; }
  .btn.ghost:hover { background:rgba(255,255,255,.09); box-shadow:none; }
  .btn.danger { background:linear-gradient(135deg,#e5484d,#b91c1c);
    box-shadow:0 6px 18px rgba(229,72,77,.25); }
  .btn.sm { padding:6px 12px; font-size:12px; border-radius:8px; }
  .btn.sm.ghost { background:rgba(255,255,255,.04); }

  /* ---------- 徽标 ---------- */
  .pill { display:inline-flex; align-items:center; gap:7px; padding:4px 12px; border-radius:99px;
    font-size:12px; font-weight:600; background:rgba(255,255,255,.06);
    border:1px solid var(--line); color:#c6d0e4; }
  .pill i { width:7px; height:7px; border-radius:50%; background:currentColor; flex:0 0 auto; }
  .pill-ok { color:var(--ok); border-color:rgba(61,220,151,.3); background:rgba(61,220,151,.08); }
  .pill-bad { color:var(--bad); border-color:rgba(255,107,107,.3); background:rgba(255,107,107,.08); }
  .pill-run { color:var(--info); border-color:rgba(90,209,255,.3); background:rgba(90,209,255,.08); }
  .spill { display:inline-flex; align-items:center; padding:2px 9px; border-radius:99px;
    font-size:11px; font-weight:600; margin:0 4px 4px 0; }
  .spill.downloaded { background:rgba(61,220,151,.12); color:#6ee7b7; }
  .spill.existed { background:rgba(90,209,255,.12); color:#93d7ff; }
  .spill.failed { background:rgba(255,107,107,.12); color:#fca5a5; }
  .spill.dead { background:rgba(148,163,200,.12); color:#9aa5bd; }
  .spill.skipped { background:rgba(148,163,200,.10); color:#aab4cb; }
  .spill.retried { background:rgba(255,194,75,.12); color:#fcd34d; }
  .spill.src { background:rgba(154,107,255,.12); color:#c4a7ff; }

  /* ---------- 状态卡 ---------- */
  .kv { display:flex; flex-direction:column; gap:10px; font-size:13px; }
  .kv-row { display:flex; justify-content:space-between; align-items:center; gap:12px; flex-wrap:wrap; }
  .kv-row .k { color:var(--muted); }
  .kv-row .v { font-weight:600; text-align:right; }
  .bar { display:flex; gap:10px; margin-top:16px; align-items:center; flex-wrap:wrap; }
  .run-state { font-size:12.5px; color:var(--warn); min-height:16px; margin-top:10px; }

  /* ---------- 统计 ---------- */
  .stats-grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(92px,1fr)); gap:12px; }
  .stat { background:rgba(255,255,255,.03); border:1px solid var(--line); border-radius:14px;
    padding:16px 10px; text-align:center; transition:transform .18s ease; }
  .stat:hover { transform:translateY(-2px); }
  .stat .n { font-size:26px; font-weight:700; line-height:1.1; font-variant-numeric:tabular-nums; }
  .stat .l { font-size:11px; color:var(--muted); margin-top:6px; }
  .c-ok { color:var(--ok); } .c-bad { color:var(--bad); } .c-warn { color:var(--warn); }
  .c-info { color:var(--info); } .c-muted { color:var(--muted); }

  /* ---------- 表格 ---------- */
  .tbl-wrap { max-height:420px; overflow:auto; border-radius:10px; border:1px solid var(--line); }
  table { width:100%; border-collapse:collapse; font-size:13px; }
  th,td { text-align:left; padding:9px 12px; border-bottom:1px solid var(--line); }
  tr:last-child td { border-bottom:0; }
  th { color:var(--muted); font-weight:500; font-size:11.5px; position:sticky; top:0;
    background:#131828; z-index:1; text-transform:uppercase; letter-spacing:.4px; }
  tr:hover td { background:rgba(109,141,255,.05); }
  .run-stats { font-size:12px; }

  /* ---------- 输入 ---------- */
  .input { width:100%; background:rgba(8,11,20,.6); border:1px solid var(--line);
    border-radius:10px; padding:10px 14px; color:var(--txt); font-size:13px;
    outline:none; transition:border-color .15s, box-shadow .15s; }
  .input:focus { border-color:var(--accent); box-shadow:0 0 0 3px rgba(109,141,255,.15); }
  .input::placeholder { color:#5a6a88; }
  .search-bar { display:flex; gap:10px; margin-bottom:12px; }
  .search-bar .input { flex:1; }
  .search-status { font-size:12.5px; color:var(--muted); min-height:18px; margin-bottom:8px; }

  /* ---------- 登录门 ---------- */
  .gate { position:fixed; inset:0; z-index:100; display:flex; align-items:center;
    justify-content:center; background:rgba(7,9,16,.86); backdrop-filter:blur(20px);
    -webkit-backdrop-filter:blur(20px); transition:opacity .35s ease, visibility .35s; }
  .gate.gate-hide { opacity:0; visibility:hidden; pointer-events:none; }
  .gate-card { width:min(420px,92vw); background:linear-gradient(180deg,rgba(30,38,64,.92),rgba(18,23,42,.94));
    border:1px solid var(--line); border-radius:22px; padding:40px 32px 30px;
    text-align:center; box-shadow:0 30px 80px rgba(0,0,0,.5); animation:fadeUp .35s ease; }
  .logo-big { width:64px; height:64px; margin:0 auto 18px; border-radius:18px;
    background:linear-gradient(135deg,var(--accent),var(--accent2)); color:#fff; font-size:30px;
    display:flex; align-items:center; justify-content:center;
    box-shadow:0 10px 30px rgba(109,141,255,.35); }
  .gate-title { font-size:22px; margin:0 0 6px; font-weight:700; }
  .gate-sub { color:var(--muted); font-size:13px; line-height:1.7; margin:0 0 22px; }
  .qr-img img { width:200px; height:200px; border-radius:14px; background:#fff; padding:8px;
    margin:16px auto 0; display:block; animation:fadeUp .3s ease; }
  .qr-tip { font-size:12.5px; color:var(--muted); margin-top:12px; min-height:18px; }
  .link-btn { background:none; border:0; color:var(--accent); cursor:pointer; font-size:12.5px;
    margin-top:18px; opacity:.85; }
  .link-btn:hover { opacity:1; text-decoration:underline; }

  /* ---------- 弹窗 ---------- */
  .modal { position:fixed; inset:0; z-index:90; background:rgba(5,7,14,.7);
    backdrop-filter:blur(8px); -webkit-backdrop-filter:blur(8px);
    display:flex; align-items:center; justify-content:center; animation:fadeIn .2s ease; }
  @keyframes fadeIn { from { opacity:0; } to { opacity:1; } }
  .modal-content { width:min(720px,94vw); max-height:86vh; overflow:auto;
    background:linear-gradient(180deg,#161c32,#10152a); border:1px solid var(--line);
    border-radius:18px; padding:26px 28px; box-shadow:0 30px 90px rgba(0,0,0,.55);
    animation:fadeUp .25s ease; }
  .modal-head { display:flex; justify-content:space-between; align-items:center; margin-bottom:6px; }
  .modal-head h2 { font-size:16px; margin:0; }
  .cfg-sep { font-size:11.5px; color:#8899cc; border-bottom:1px solid var(--line);
    padding:16px 0 6px; margin:4px 0 12px; text-transform:uppercase; letter-spacing:1px; }
  .cfg-group { display:flex; flex-direction:column; gap:5px; flex:1; min-width:120px; margin-bottom:12px; }
  .cfg-group label { font-size:12px; color:var(--muted); }
  .cfg-row { display:flex; gap:12px; align-items:flex-end; flex-wrap:wrap; }
  .cfg-cb { font-size:13px; display:flex; align-items:center; gap:7px; cursor:pointer;
    padding:2px 0; user-select:none; }
  .cfg-cb input[type=checkbox] { width:15px; height:15px; accent-color:var(--accent); cursor:pointer; }
  .adv { margin-top:16px; }
  .adv summary { cursor:pointer; font-size:12.5px; color:var(--muted); }
  textarea.input.mono { font-family:ui-monospace,Consolas,monospace; font-size:12px;
    height:220px; margin-top:10px; resize:vertical; }

  /* ---------- Toast ---------- */
  #toasts { position:fixed; right:20px; bottom:20px; z-index:200;
    display:flex; flex-direction:column; gap:10px; }
  .toast { background:rgba(24,30,52,.96); border:1px solid var(--line);
    border-left:3px solid var(--accent); padding:12px 16px; border-radius:10px;
    font-size:13px; box-shadow:0 12px 32px rgba(0,0,0,.4);
    animation:slideIn .25s ease; max-width:340px; }
  .toast.ok { border-left-color:var(--ok); }
  .toast.bad { border-left-color:var(--bad); }
  .toast.warn { border-left-color:var(--warn); }
  @keyframes slideIn { from { opacity:0; transform:translateX(16px); } to { opacity:1; transform:none; } }
</style>
</head>
<body>

<div id="gate" class="gate">
  <div class="gate-card">
    <div class="logo-big">♪</div>
    <h1 class="gate-title">Navidrome Sync</h1>
    <div id="gate-body">
      <p class="gate-sub">正在检查登录状态…</p>
    </div>
    <button class="link-btn" id="gate-skip" onclick="skipGate()" style="visibility:hidden">跳过登录，先浏览 →</button>
  </div>
</div>

<header class="topbar">
  <div class="brand">
    <div class="logo">♪</div>
    <div>
      <div class="brand-name">Navidrome <span>Sync</span></div>
      <div class="brand-sub">曲库自动同步助手</div>
    </div>
  </div>
  <div class="topbar-right">
    <span id="ck-pill" class="pill"><i></i>检查中…</span>
    <button class="btn ghost sm hide" id="login-btn" onclick="openGate()">登录</button>
    <button class="btn ghost sm" onclick="showConfig()">⚙ 设置</button>
  </div>
</header>

<main>
  <section class="grid-two">
    <div class="card">
      <div class="card-head"><h2>运行状态</h2><span id="run-badge" class="pill"><i></i>空闲</span></div>
      <div class="kv" id="status"></div>
      <div class="bar">
        <button class="btn" id="run-btn" onclick="triggerRun()">▶ 立即运行</button>
        <button class="btn danger hide" id="stop-btn" onclick="stopRun()">■ 停止</button>
        <button class="btn ghost" id="refresh-btn" onclick="toggleRefresh()">⏸ 暂停自动刷新</button>
      </div>
      <div id="run-state" class="run-state"></div>
    </div>
    <div class="card">
      <div class="card-head"><h2>曲目统计</h2></div>
      <div class="stats-grid" id="stats"></div>
    </div>
  </section>

  <section class="card">
    <div class="card-head"><h2>搜索下载</h2><span class="card-tip">搜到即可一键下载入库</span></div>
    <div class="search-bar">
      <input id="search-query" class="input" placeholder="搜索歌曲、歌手…"
             onkeydown="if(event.key==='Enter')doSearch()">
      <button class="btn" onclick="doSearch()">搜索</button>
    </div>
    <div id="search-status" class="search-status"></div>
    <div class="tbl-wrap"><table id="search-results"></table></div>
  </section>

  <section class="grid-three">
    <div class="card">
      <div class="card-head"><h2>最近运行</h2></div>
      <div class="tbl-wrap"><table id="runs"></table></div>
    </div>
    <div class="card">
      <div class="card-head"><h2>最近入库</h2></div>
      <div class="tbl-wrap"><table id="downloaded"></table></div>
    </div>
    <div class="card">
      <div class="card-head"><h2>失败 / 重试队列</h2></div>
      <div class="tbl-wrap"><table id="failed"></table></div>
    </div>
  </section>
</main>

<footer class="footer">netease-navidrome-sync · 仅供个人学习使用</footer>

<div id="toasts"></div>

<script>
const fmt = ts => ts ? new Date(ts*1000).toLocaleString('zh-CN',{hour12:false}) : '-';
let autoRefresh = true, qrTimer = null, gateDone = false;

function toast(msg, type='') {
  const box = document.getElementById('toasts');
  const el = document.createElement('div');
  el.className = 'toast ' + type;
  el.textContent = msg;
  box.appendChild(el);
  setTimeout(() => { el.style.opacity='0'; el.style.transition='opacity .3s';
    setTimeout(() => el.remove(), 300); }, 3200);
}

function spill(s) {
  return `<span class="spill ${s}">${({downloaded:'已下',existed:'已有',skipped:'跳过',failed:'失败',dead:'放弃',pending:'待处理'})[s]||s}</span>`;
}
function statBox(n, label, cls='') {
  return `<div class="stat"><div class="n ${cls}">${n}</div><div class="l">${label}</div></div>`;
}
function runSummary(stats) {
  let s = stats || {};
  let html = '';
  for (const k of ['downloaded','existed','skipped','failed','retried']) {
    if (s[k]) html += `<span class="spill ${k}">${({downloaded:'已下',existed:'已有',skipped:'跳过',failed:'失败',retried:'重试'})[k]} ${s[k]}</span>`;
  }
  if (s.duration_s) html += `<span class="muted"> ${s.duration_s}s</span>`;
  if (s.cookie_ok === false) html += `<span class="spill failed">Cookie失效</span>`;
  if (s.aborted) html += `<span class="spill retried">已中止</span>`;
  if (s.error) html += `<span class="spill failed">错误</span>`;
  return html || '<span class="muted">无数据</span>';
}

async function load() {
  if (!autoRefresh) return;
  let st;
  try { st = await (await fetch('/api/status')).json(); } catch(e) { return; }

  if (!gateDone && st.cookie_ok !== true) showGateLogin();
  else if (!gateDone) closeGate();

  const ckPill = document.getElementById('ck-pill');
  const loginBtn = document.getElementById('login-btn');
  if (st.cookie_ok) {
    ckPill.className = 'pill pill-ok'; ckPill.innerHTML = '<i></i>网易云已登录';
    loginBtn.classList.add('hide');
  } else {
    ckPill.className = 'pill pill-bad'; ckPill.innerHTML = '<i></i>网易云未登录';
    loginBtn.classList.remove('hide');
  }

  const badge = document.getElementById('run-badge');
  badge.className = 'pill ' + (st.running ? 'pill-run' : '');
  badge.innerHTML = st.running ? '<i></i>运行中' : '<i></i>空闲';
  document.getElementById('status').innerHTML = `
    <div class="kv-row"><span class="k">下载源链</span><span class="v">${st.dl_sources.join(' → ')}</span></div>
    <div class="kv-row"><span class="k">推荐源</span><span class="v">${st.enabled_sources.join('、') || '无'}</span></div>
    <div class="kv-row"><span class="k">听歌同步</span><span class="v">${st.scrobble || '<span class="muted">-</span>'}</span></div>
    <div class="kv-row"><span class="k">下次运行</span><span class="v">${st.next_run || '未知'}</span></div>
    <div class="kv-row"><span class="k">上次运行</span><span class="v">${fmt(st.last_run)}</span></div>`;
  document.getElementById('run-btn').disabled = st.running;
  document.getElementById('stop-btn').classList.toggle('hide', !st.running);
  document.getElementById('run-state').textContent = st.running ? '任务运行中…' : '';

  const stats = await (await fetch('/api/stats')).json();
  document.getElementById('stats').innerHTML =
    statBox(stats.downloaded||0,'已下载','c-ok') +
    statBox(stats.existed||0,'已存在','c-info') +
    statBox(stats.failed||0,'失败','c-bad') +
    statBox(stats.dead||0,'放弃','c-muted') +
    statBox(stats.pending||0,'待处理','c-warn');

  const runs = await (await fetch('/api/runs')).json();
  document.getElementById('runs').innerHTML =
    '<tr><th>时间</th><th>结果</th></tr>' + runs.map(r =>
      `<tr><td class="muted">${fmt(r.started_at)}</td>
       <td class="run-stats">${runSummary(typeof r.stats==='string'?JSON.parse(r.stats||'{}'):r.stats)}</td></tr>`).join('');

  const dl = await (await fetch('/api/tracks?status=downloaded&limit=200')).json();
  document.getElementById('downloaded').innerHTML =
    '<tr><th>曲目</th><th>歌单</th><th>源</th></tr>' + dl.map(t =>
      `<tr><td>${t.artists.join('/')} - ${t.title}</td><td class="muted">${t.playlist||'-'}</td>
       <td><span class="spill src">${t.download_source}</span></td></tr>`).join('');

  const failed = await (await fetch('/api/tracks?status=failed&limit=200')).json();
  const dead = await (await fetch('/api/tracks?status=dead&limit=50')).json();
  document.getElementById('failed').innerHTML =
    '<tr><th>曲目</th><th>原因</th><th>次</th><th>下次重试</th><th></th></tr>' +
    failed.concat(dead).map(t =>
      `<tr><td>${t.artists.join('/')} - ${t.title}</td>
       <td class="muted">${t.fail_reason}</td><td>${t.attempts}</td>
       <td class="muted">${fmt(t.next_retry_at)}</td>
       <td><button class="btn ghost sm" onclick="retry(${t.id})">重试</button></td></tr>`).join('');
}

async function triggerRun() {
  const btn = document.getElementById('run-btn');
  if (btn.disabled) return;
  const r = await (await fetch('/api/run', {method:'POST'})).json();
  if (r.ok) {
    btn.disabled = true; btn.textContent = '运行中…';
    toast('每日任务已开始', 'ok');
    setTimeout(load, 1500);
  } else {
    toast(r.msg || '启动失败', 'bad');
  }
}
async function stopRun() {
  const r = await (await fetch('/api/stop', {method:'POST'})).json();
  if (r.ok) toast('已请求中止（下一首曲目前生效）', 'warn');
  else toast(r.msg || '操作失败', 'bad');
  setTimeout(load, 2000);
}
function toggleRefresh() {
  autoRefresh = !autoRefresh;
  const btn = document.getElementById('refresh-btn');
  btn.textContent = autoRefresh ? '⏸ 暂停自动刷新' : '▶ 恢复自动刷新';
  btn.classList.toggle('ghost', autoRefresh);
  if (autoRefresh) load();
}
async function retry(id) {
  await fetch('/api/retry/'+id, {method:'POST'});
  toast('已加入重试队列', 'ok');
  load();
}

/* ---------- 登录门 ---------- */
function showGateLogin() {
  document.getElementById('gate-body').innerHTML = `
    <p class="gate-sub">登录网易云后，每天自动拉取日推、同步歌单</p>
    <button class="btn" onclick="qrStart()">显示二维码</button>
    <div id="qr-img"></div>
    <div id="qr-tip" class="qr-tip"></div>`;
  document.getElementById('gate-skip').style.visibility = 'visible';
}
function closeGate() {
  gateDone = true;
  document.getElementById('gate').classList.add('gate-hide');
}
function skipGate() { closeGate(); }
function openGate() {
  gateDone = false;
  document.getElementById('gate').classList.remove('gate-hide');
  showGateLogin();
}
async function qrStart() {
  const tip = document.getElementById('qr-tip');
  if (!tip) return;
  tip.innerHTML = '生成二维码…';
  const r = await (await fetch('/api/qr/start')).json();
  if (!r.ok) { tip.innerHTML = '<span class="bad">'+r.msg+'</span>'; return; }
  document.getElementById('qr-img').innerHTML = '<img src="'+r.qrimg+'" alt="二维码">';
  tip.innerHTML = '请用 <b>网易云音乐 App</b> 扫码';
  if (qrTimer) clearInterval(qrTimer);
  qrTimer = setInterval(() => qrPoll(r.key), 2000);
}
async function qrPoll(key) {
  const r = await (await fetch('/api/qr/poll?key='+encodeURIComponent(key))).json();
  const tip = document.getElementById('qr-tip');
  if (!tip) { clearInterval(qrTimer); qrTimer = null; return; }
  if (r.status === 801) tip.innerHTML = '等待扫码…';
  else if (r.status === 802) tip.innerHTML = '<span class="warn">已扫码，请在手机上确认登录</span>';
  else if (r.status === 803) {
    clearInterval(qrTimer); qrTimer = null;
    tip.innerHTML = '<span class="ok">✓ 登录成功</span>';
    toast('网易云登录成功', 'ok');
    closeGate();
    load();
  } else if (r.status === 800) {
    tip.innerHTML = '<span class="bad">二维码已过期，请重新生成</span>';
    clearInterval(qrTimer); qrTimer = null;
  } else {
    tip.innerHTML = '<span class="bad">扫码不可用 ('+r.status+')</span>';
  }
}

/* ---------- 搜索下载 ---------- */
async function doSearch() {
  const q = document.getElementById('search-query').value.trim();
  if (!q) return;
  const status = document.getElementById('search-status');
  status.textContent = '搜索中…';
  const r = await (await fetch('/api/search?q='+encodeURIComponent(q)+'&limit=30')).json();
  if (r.error) { status.innerHTML = '<span class="bad">'+r.error+'</span>'; return; }
  if (!r.length) { status.textContent = '无结果'; document.getElementById('search-results').innerHTML = ''; return; }
  status.textContent = '找到 '+r.length+' 首';
  document.getElementById('search-results').innerHTML =
    '<tr><th>曲名</th><th>歌手</th><th>专辑</th><th></th></tr>' +
    r.map(s => {
      const artists = s.artists.join('/');
      return `<tr><td>${s.name}</td><td class="muted">${artists}</td><td class="muted">${s.album||'-'}</td>
        <td><button class="btn ghost sm" onclick="dlSong('${encodeURIComponent(s.artists[0]||'')}','${encodeURIComponent(s.name)}')">下载</button></td></tr>`;
    }).join('');
}
async function dlSong(artist, title) {
  const a = decodeURIComponent(artist), t = decodeURIComponent(title);
  toast('开始下载: '+a+' - '+t);
  const r = await (await fetch('/api/download', {method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({artist: a, title: t})})).json();
  if (r.ok) toast('✓ 下载完成: '+r.file, 'ok');
  else toast('✗ 下载失败: '+(r.msg||''), 'bad');
  load();
}

/* ---------- 配置弹窗 ---------- */
function showConfig() {
  const html = `
    <div class="modal-head"><h2>⚙ 配置</h2><button class="btn ghost sm" onclick="hideModal()">✕ 关闭</button></div>
    <div class="cfg-sep">Navidrome 查重</div>
    <div class="cfg-group"><label>地址</label><input id="c-nav-url" class="input" placeholder="http://192.168.1.10:4533"></div>
    <div class="cfg-row">
      <div class="cfg-group"><label>用户名</label><input id="c-nav-user" class="input"></div>
      <div class="cfg-group"><label>密码</label><input id="c-nav-pass" class="input" type="password"></div>
    </div>
    <div class="cfg-sep">推荐源</div>
    <div class="cfg-row">
      <label class="cfg-cb"><input type="checkbox" id="c-lb-en" onchange="cfgToggle('c-lb-un')"> ListenBrainz</label>
      <input id="c-lb-un" class="input" placeholder="用户名" style="width:190px" disabled>
    </div>
    <div class="cfg-row">
      <label class="cfg-cb"><input type="checkbox" id="c-lf-en" onchange="cfgToggle('c-lf-k');cfgToggle('c-lf-u')"> Last.fm</label>
      <input id="c-lf-k" class="input" placeholder="API Key" style="width:180px" disabled>
      <input id="c-lf-u" class="input" placeholder="用户名" style="width:150px" disabled>
    </div>
    <div class="cfg-row">
      <label class="cfg-cb"><input type="checkbox" id="c-dd-en"> 网易云日推</label>
      <label class="cfg-cb"><input type="checkbox" id="c-pl-en"> 网易云歌单同步</label>
    </div>
    <div class="cfg-sep">下载</div>
    <div class="cfg-row" style="flex-wrap:wrap" id="c-dl-srcs"></div>
    <div class="cfg-row">
      <div class="cfg-group"><label>匹配阈值</label><input id="c-th" class="input" style="width:90px" type="number"></div>
      <div class="cfg-group"><label>时长差(秒)</label><input id="c-dur" class="input" style="width:90px" type="number"></div>
      <div class="cfg-group"><label>下载间隔(秒)</label><input id="c-int" class="input" style="width:90px" type="number"></div>
    </div>
    <div class="cfg-sep">调度</div>
    <div class="cfg-group"><label>Cron 表达式</label><input id="c-cron" class="input" placeholder="30 4 * * *"></div>
    <details class="adv"><summary>高级 → 完整 YAML</summary>
      <textarea id="c-yaml" class="input mono"></textarea>
    </details>
    <div class="bar">
      <button class="btn" onclick="saveConfig()">保存</button>
      <button class="btn ghost" onclick="hideModal()">取消</button>
      <span id="cfg-st"></span>
    </div>`;
  showModal(html);
  document.getElementById('cfg-st').textContent = '加载中…';
  fetch('/api/config').then(r=>r.text()).then(t => {
    const y = parseYaml(t);
    setVal('c-nav-url', y.navidrome?.url); setVal('c-nav-user', y.navidrome?.username); setVal('c-nav-pass', y.navidrome?.password);
    setCb('c-lb-en', y.sources?.listenbrainz?.enabled);
    setVal('c-lb-un', y.sources?.listenbrainz?.username);
    setCb('c-lf-en', y.sources?.lastfm?.enabled);
    setVal('c-lf-k', y.sources?.lastfm?.api_key); setVal('c-lf-u', y.sources?.lastfm?.username);
    setCb('c-dd-en', y.sources?.netease_daily?.enabled); setCb('c-pl-en', y.sources?.netease_playlists?.enabled);
    const srcs = ['ytdlp','netease','kuwo','migu','bodian','qq'];
    const act = (y.download?.sources || []);
    document.getElementById('c-dl-srcs').innerHTML = srcs.map(s =>
      `<label class="cfg-cb"><input type="checkbox" value="${s}" ${act.includes(s)?'checked':''}> ${s}</label>`
    ).join('');
    setVal('c-th', y.download?.title_threshold); setVal('c-dur', y.download?.max_duration_diff);
    setVal('c-int', y.download?.interval_seconds); setVal('c-cron', y.schedule?.cron);
    document.getElementById('c-yaml').value = t;
    document.getElementById('cfg-st').textContent = '';
  });
}
function cfgToggle(id) { document.getElementById(id).disabled = !document.getElementById(id.replace('-k','-en').replace('-u','-en')).checked; }
function setVal(id, v) { const e=document.getElementById(id); if(e && v!==undefined) e.value=v; }
function setCb(id, v) { const e=document.getElementById(id); if(e) e.checked=!!v; }
function parseYaml(t) {
  const o={}; let sec=null;
  t.split('\\n').forEach(l => {
    const m = l.match(/^(\\S[^:]*):/); if(m) sec=m[1];
    if(sec && l.match(/^\\s+(\\w+):\\s*(.*)/)) { const k=RegExp.$1,v=RegExp.$2; o[sec]||(o[sec]={}); o[sec][k]=v.replace(/^['"]|['"]$/g,''); }
    if(!l.trim().startsWith('#')&&l.includes(': ')) {
      const parts=l.split(': '); if(parts.length==2&&!l.startsWith(' ')) o[parts[0]]=parts[1].replace(/^['"]|['"]$/g,'');
    }
  });
  return o;
}
async function saveConfig() {
  const g = id => document.getElementById(id);
  const v = id => g(id)?.value||'';
  const c = id => g(id)?.checked||false;
  const srcs = Array.from(document.querySelectorAll('#c-dl-srcs input:checked')).map(e=>e.value);
  const body = {
    navidrome: {url: v('c-nav-url'), username: v('c-nav-user'), password: v('c-nav-pass')},
    sources: {
      netease_daily: {enabled: c('c-dd-en')},
      netease_playlists: {enabled: c('c-pl-en')},
      listenbrainz: {enabled: c('c-lb-en'), username: v('c-lb-un')},
      lastfm: {enabled: c('c-lf-en'), api_key: v('c-lf-k'), username: v('c-lf-u')}
    },
    download: {sources: srcs, interval_seconds: parseFloat(v('c-int'))||2,
               title_threshold: parseInt(v('c-th'))||85, max_duration_diff: parseInt(v('c-dur'))||12},
    schedule: {cron: v('c-cron')||'30 4 * * *'},
  };
  const r = await (await fetch('/api/config', {method:'PUT', headers:{'Content-Type':'application/json'}, body: JSON.stringify(body)})).json();
  if (r.ok) { toast('✓ 配置已保存并热生效', 'ok'); hideModal(); load(); }
  else toast('✗ 保存失败: '+(r.msg||''), 'bad');
}
function hideModal() { const m = document.querySelector('.modal'); if(m) m.remove(); }
function showModal(html) {
  const m = document.createElement('div'); m.className='modal'; m.innerHTML='<div class="modal-content">'+html+'</div>';
  m.addEventListener('click', e => { if(e.target===m) m.remove(); });
  document.body.appendChild(m);
}

load();
setInterval(load, 30000);
</script>
</body>
</html>
"""


def _live_cookie_ok(jobs) -> bool | None:
    """定期校验 Cookie；网络不可用时返回 None，而不是误报失效。"""
    if (time.time() - getattr(jobs, "last_cookie_check_at", 0.0) > 300
            or jobs.last_cookie_ok is None):
        try:
            jobs.refresh_cookie_status()
        except Exception:
            pass
    return jobs.last_cookie_ok


def create_app(cfg, db, jobs, scheduler=None):
    app = FastAPI(title="navidrome-sync")

    @app.middleware("http")
    async def basic_auth(request: Request, call_next):
        """可选 Basic Auth：配置了 web.auth_user 时才启用，未配置保持开放。"""
        if not cfg.web_auth_user:
            return await call_next(request)
        header = request.headers.get("authorization", "")
        ok = False
        if header.startswith("Basic "):
            try:
                raw = base64.b64decode(header[6:]).decode("utf-8")
                user, _, pwd = raw.partition(":")
                ok = (hmac.compare_digest(user, cfg.web_auth_user)
                      and hmac.compare_digest(pwd, cfg.web_auth_password))
            except Exception:
                ok = False
        if not ok:
            return JSONResponse({"detail": "需要登录"},
                                status_code=401,
                                headers={"WWW-Authenticate": 'Basic realm="navidrome-sync"'})
        return await call_next(request)

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
            "cookie_ok": _live_cookie_ok(jobs),
            "dl_sources": cfg.dl_sources,
            "enabled_sources": enabled,
            "next_run": next_run,
            "last_run": runs[0]["started_at"] if runs else None,
            "running": jobs._lock.locked(),
            "aborted": jobs.aborted,
            "last_aborted": bool(last_stats.get("aborted")),
            "scrobble": _scrobble_status(last_stats),
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

    @app.get("/api/config")
    def get_config():
        try:
            return JSONResponse(content=cfg._path.read_text(encoding="utf-8"))
        except Exception as e:
            return {"ok": False, "msg": str(e)}

    @app.put("/api/config")
    async def put_config(req: Request):
        try:
            import yaml
            updates = await req.json()
        except Exception as e:
            return {"ok": False, "msg": f"请求格式错误: {e}"}
        try:
            raw = cfg._raw.copy() if isinstance(cfg._raw, dict) else {}
            def merge(d, u):
                for k, v in u.items():
                    if isinstance(v, dict) and isinstance(d.get(k), dict):
                        merge(d[k], v)
                    elif isinstance(v, list) and not v and isinstance(d.get(k), list):
                        # 空列表不覆盖已有配置，防止表单把歌单等列表清空
                        continue
                    else:
                        d[k] = v
            merge(raw, updates)
            cfg._path.write_text(yaml.dump(raw, default_flow_style=False, allow_unicode=True, sort_keys=False), encoding="utf-8")
            from . import config as config_mod
            new_cfg = config_mod.load()
            for at in ("music_dir","data_dir","ncm_api_url","cron","discover_daily_limit",
                       "dl_sources","dl_interval",
                       "title_threshold","max_duration_diff","run_on_startup",
                       "web_host","web_port","web_auth_user","web_auth_password"):
                setattr(cfg, at, getattr(new_cfg, at))
            cfg.navidrome = new_cfg.navidrome
            cfg.sources = new_cfg.sources
            if cfg.netease_cookie != new_cfg.netease_cookie:
                cfg.netease_cookie = new_cfg.netease_cookie
                jobs.set_cookie(cfg.netease_cookie)
            jobs.apply_engine_config()
            jobs.reload_navidrome()
            if scheduler:
                try:
                    parts = cfg.cron.split()
                    from apscheduler.triggers.cron import CronTrigger
                    scheduler.reschedule_job("daily_sync", trigger=CronTrigger(
                        minute=parts[0], hour=parts[1], day=parts[2],
                        month=parts[3], day_of_week=parts[4]))
                except Exception:
                    pass
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "msg": str(e)}

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

    @app.get("/api/search")
    def search(q: str = "", limit: int = 30):
        ncm = getattr(app.state, "ncm_client", None)
        if not ncm:
            return {"error": "网易云后端未连接"}
        try:
            return ncm.search(q, limit)
        except Exception as e:
            return {"error": str(e)}

    @app.post("/api/download")
    async def download(req: Request):
        ncm = getattr(app.state, "ncm_client", None)
        engine = getattr(app.state, "engine", None)
        if not ncm or not engine:
            return {"ok": False, "msg": "后端未就绪"}
        body = await req.json()
        artist = str(body.get("artist", ""))
        title = str(body.get("title", ""))
        if not artist or not title:
            return {"ok": False, "msg": "缺少 artist/title"}
        try:
            from pathlib import Path as P
            from .downloader import (DownloadError, embed_metadata, move_file)
            from .util import safe_name, RateLimiter
            from .sources.base import Track
            from .matcher import best_match
            track = Track(title=title, artists=[artist] if artist else [],
                          origin="manual_search", playlist="手动搜索")
            ncm_limiter = RateLimiter(0.5)
            ncm_limiter.wait()
            candidates = ncm.search(f"{artist} {title}", limit=10)
            hit = best_match(track, candidates)
            if hit:
                track.ncm_id = hit["id"]; track.title = hit["name"]
                track.artists = hit["artists"]; track.album = hit.get("album", "")
                ncm_limiter.wait()
                olrc, tlrc = ncm.lyric(track.ncm_id)
                from .jobs import _merge_lrc
                lyrics_text = _merge_lrc(olrc, tlrc) if olrc else None
            else:
                lyrics_text = None
            audio_path, dl_source = engine.download(track)
            ext = audio_path.suffix.lower()
            subdir = P("Discover")
            fname = safe_name(' - '.join(track.artists) + ' - ' + track.title) + ext
            dest = P(cfg.music_dir) / subdir / fname
            embed_metadata(audio_path, track, "", lyrics_text)
            move_file(audio_path, dest)
            if lyrics_text:
                from .library import write_lrc_sidecar
                write_lrc_sidecar(dest, lyrics_text)
            return {"ok": True, "file": str(subdir / fname)}
        except Exception as e:
            import traceback; traceback.print_exc()
            return {"ok": False, "msg": str(e)}

    return app
