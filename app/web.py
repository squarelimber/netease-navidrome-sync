"""状态页：FastAPI 单页应用 + JSON API。"""

from __future__ import annotations

import base64
import hmac
import json
import logging
import threading
import time

import yaml

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


PAGE = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>nsync — 曲库同步</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Cormorant+Garamond:ital,wght@0,500;0,600;0,700;1,500&display=swap" rel="stylesheet">
<style>
  :root { color-scheme: dark;
    --bg:#131110; --bg2:#1a1817; --bg3:#221f1d;
    --line:rgba(236,228,214,.10); --line2:rgba(236,228,214,.22);
    --txt:#e9e2d4; --dim:#9d9384; --faint:#6d655a;
    --accent:#d43c33; --ok:#84a98c; --warn:#c29a55; --bad:#c96157; --src:#b49c74;
    --serif:'Cormorant Garamond','Songti SC','STSong',Georgia,serif;
    --sans:-apple-system,BlinkMacSystemFont,'Segoe UI','PingFang SC','HarmonyOS Sans SC','Microsoft YaHei',sans-serif;
    --mono:ui-monospace,'SF Mono','Cascadia Mono',Consolas,'Courier New',monospace; }
  * { box-sizing:border-box; }
  html { scrollbar-width:thin; scrollbar-color:rgba(236,228,214,.18) transparent; }
  body { margin:0; min-height:100vh; background:var(--bg); color:var(--txt);
    font:14px/1.65 var(--sans); -webkit-font-smoothing:antialiased; }
  ::selection { background:rgba(212,60,51,.35); }
  ::-webkit-scrollbar { width:10px; height:10px; }
  ::-webkit-scrollbar-thumb { background:rgba(236,228,214,.14); border-radius:5px; }
  ::-webkit-scrollbar-thumb:hover { background:rgba(236,228,214,.26); }
  /* 纸张颗粒，非渐变光晕 */
  .grain { position:fixed; inset:0; z-index:1; pointer-events:none; opacity:.05; mix-blend-mode:overlay;
    background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='140' height='140'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.85' numOctaves='2'/%3E%3C/filter%3E%3Crect width='140' height='140' filter='url(%23n)' opacity='0.7'/%3E%3C/svg%3E"); }
  .hide { display:none !important; }
  .muted { color:var(--dim); } .faint { color:var(--faint); }
  .ok { color:var(--ok); } .bad { color:var(--bad); } .warn { color:var(--warn); }
  a { color:inherit; }
  button { font-family:inherit; }

  /* ---------- 顶栏：一条线，不是玻璃条 ---------- */
  .topbar { position:sticky; top:0; z-index:50; display:flex; align-items:center;
    justify-content:space-between; gap:14px; padding:15px 30px;
    background:var(--bg); border-bottom:1px solid var(--line); }
  .brand { display:flex; align-items:baseline; gap:11px; user-select:none; }
  .wordmark { font-family:var(--serif); font-size:23px; font-weight:700; letter-spacing:.5px; }
  .wordmark i { font-style:normal; color:var(--accent); }
  .brand-sub { font:11px/1 var(--mono); color:var(--faint); letter-spacing:2.5px; }
  .topbar-right { display:flex; align-items:center; gap:18px; }
  .ck { display:inline-flex; align-items:center; gap:8px; font:12px/1 var(--mono); color:var(--dim); }
  .dot { width:7px; height:7px; border-radius:50%; flex:0 0 auto; }
  .dot-on { background:var(--ok); box-shadow:0 0 0 3px rgba(132,169,140,.14); }
  .dot-off { background:transparent; border:1.5px solid var(--bad); }
  .dot-warn { background:transparent; border:1.5px solid var(--warn); }
  .top-actions { display:flex; align-items:center; gap:16px; }
  .txt-btn { background:none; border:0; cursor:pointer; font:12px/1 var(--mono);
    color:var(--dim); letter-spacing:1px; padding:6px 2px; border-bottom:1px solid transparent;
    transition:color .15s, border-color .15s; }
  .txt-btn:hover { color:var(--txt); border-bottom-color:var(--line2); }
  .txt-btn.danger:hover { color:var(--bad); }

  /* ---------- 布局 ---------- */
  .shell { position:relative; z-index:2; max-width:1240px; margin:0 auto;
    padding:34px 30px 30px; display:grid; grid-template-columns:212px 1fr; gap:46px; }
  .rail { position:sticky; top:86px; align-self:start; display:flex; flex-direction:column; gap:30px; }
  .rail nav { display:flex; flex-direction:column; gap:2px; }
  .rail a { font-size:13px; color:var(--dim); text-decoration:none; padding:6px 0 6px 14px;
    border-left:2px solid transparent; transition:color .15s, border-color .15s; }
  .rail a:hover { color:var(--txt); border-left-color:var(--line2); }
  .rail .rail-clock { font:12px/1.9 var(--mono); color:var(--faint); letter-spacing:.5px; }
  .rail .rail-clock b { color:var(--dim); font-weight:500; }
  @media (max-width:940px) {
    .shell { grid-template-columns:1fr; gap:26px; }
    .rail { position:static; flex-direction:row; flex-wrap:wrap; align-items:center; }
    .rail nav { flex-direction:row; gap:14px; }
    .rail a { padding:6px 0; border-left:0; }
    .rail-clock { display:none; } }

  /* ---------- 开篇：编辑式引语 ---------- */
  .intro { margin-bottom:34px; }
  .intro h1 { margin:0; font:600 40px/1.15 var(--serif); letter-spacing:.5px; }
  .intro h1 em { font-style:normal; color:var(--accent); }
  .intro p { margin:10px 0 0; color:var(--dim); font-size:13.5px; max-width:560px; }
  .statusline { margin-top:18px; padding-top:16px; border-top:1px solid var(--line);
    display:flex; align-items:center; gap:14px; flex-wrap:wrap; }
  .statusline .eq { display:inline-flex; align-items:flex-end; gap:2px; height:14px; }
  .statusline .eq span { width:2.5px; background:var(--accent); animation:eq 1s steps(2,end) infinite; }
  .statusline .eq span:nth-child(1){height:6px; animation-delay:0s;}
  .statusline .eq span:nth-child(2){height:14px; animation-delay:.2s;}
  .statusline .eq span:nth-child(3){height:9px; animation-delay:.45s;}
  .statusline .eq span:nth-child(4){height:12px; animation-delay:.1s;}
  @keyframes eq { 50% { transform:scaleY(.35); } }
  .run-badge { font:12px/1 var(--mono); letter-spacing:1.5px; display:inline-flex;
    align-items:center; gap:8px; color:var(--accent); }
  .run-badge.idle { color:var(--faint); }
  .run-state { font:12px/1 var(--mono); color:var(--warn); letter-spacing:.5px; }
  .sysline { margin-top:10px; font-size:11px; letter-spacing:1px; }

  /* ---------- 按钮 ---------- */
  .btn { display:inline-flex; align-items:center; gap:8px; background:var(--accent); color:#fff8f6;
    border:1px solid var(--accent); border-radius:2px; padding:9px 18px;
    font:600 13px/1 var(--sans); letter-spacing:.4px; cursor:pointer;
    transition:background .15s, border-color .15s, color .15s; }
  .btn:hover { background:#e0483e; border-color:#e0483e; }
  .btn:active { background:#bb342c; }
  .btn:disabled { opacity:.35; cursor:not-allowed; }
  .btn.ghost { background:transparent; border-color:var(--line2); color:var(--dim); }
  .btn.ghost:hover { background:rgba(236,228,214,.05); border-color:var(--txt); color:var(--txt); }
  .btn.danger { background:transparent; border-color:rgba(201,97,87,.5); color:var(--bad); }
  .btn.danger:hover { background:rgba(201,97,87,.12); border-color:var(--bad); }
  .btn.sm { padding:5px 12px; font-size:12px; }
  .actions { display:flex; gap:10px; flex-wrap:wrap; margin-top:18px; }

  /* ---------- 统计：大数字 + 发丝线 ---------- */
  .stats { display:grid; grid-template-columns:repeat(5,1fr); margin:30px 0 44px; }
  .stat { padding:4px 22px 4px 0; border-right:1px solid var(--line); }
  .stat:last-child { border-right:0; }
  .stat + .stat { padding-left:22px; }
  .stat .n { font-family:var(--serif); font-size:38px; font-weight:600; line-height:1.1;
    font-variant-numeric:tabular-nums; }
  .stat .l { font:11px/1 var(--mono); color:var(--faint); letter-spacing:2.5px; margin-top:9px; }
  .stat.a .n { color:var(--accent); } .stat.b .n { color:var(--ok); }
  .stat.c .n { color:var(--bad); } .stat.d .n { color:var(--dim); } .stat.e .n { color:var(--warn); }
  @media (max-width:760px) {
    .stats { grid-template-columns:repeat(3,1fr); row-gap:22px; }
    .stat { border-right:0; padding-left:0; } }

  /* ---------- 区块标题 ---------- */
  .sec { margin-bottom:46px; }
  .sec-head { display:flex; align-items:baseline; justify-content:space-between; gap:12px; margin-bottom:16px; }
  .sec-head h2 { margin:0; font:600 21px/1.2 var(--serif); letter-spacing:.3px; }
  .sec-head .no { font:11px/1 var(--mono); color:var(--accent); letter-spacing:2px; margin-right:10px; }
  .sec-tip { font:11px/1.5 var(--mono); color:var(--faint); letter-spacing:.5px; }

  /* ---------- 搜索 ---------- */
  .search-bar { display:flex; gap:0; border-bottom:1px solid var(--line2); transition:border-color .15s; }
  .search-bar:focus-within { border-bottom-color:var(--accent); }
  .search-bar input { flex:1; background:none; border:0; outline:none; padding:11px 2px;
    color:var(--txt); font:15px/1.4 var(--sans); }
  .search-bar input::placeholder { color:var(--faint); }
  .search-bar .btn { border-radius:0; border-left:1px solid var(--line2); }
  .search-status { font:12px/1 var(--mono); color:var(--faint); margin:10px 0 4px; letter-spacing:.5px; min-height:16px; }

  /* ---------- 表格：无边框，行悬停 ---------- */
  .tbl-wrap { max-height:380px; overflow:auto; }
  table { width:100%; border-collapse:collapse; font-size:13px; }
  th { font:11px/1 var(--mono); color:var(--faint); letter-spacing:1.8px; font-weight:500;
    text-align:left; padding:10px 12px; border-bottom:1px solid var(--line2);
    position:sticky; top:0; background:var(--bg); z-index:1; }
  td { padding:10px 12px; border-bottom:1px solid var(--line); vertical-align:top; }
  tr:last-child td { border-bottom:0; }
  tbody tr { transition:background .12s; }
  tbody tr:hover { background:rgba(236,228,214,.035); }
  td .t { color:var(--txt); } td .a { color:var(--dim); }
  .num { font:12px/1.6 var(--mono); font-variant-numeric:tabular-nums; }
  .tag { font:11px/1 var(--mono); color:var(--src); letter-spacing:1px; }
  .spill { display:inline-block; font:11px/1.9 var(--mono); letter-spacing:.5px;
    border:1px solid var(--line2); border-radius:2px; padding:1px 8px; margin:1px 4px 2px 0; color:var(--dim); }
  .spill.ok { color:var(--ok); border-color:rgba(132,169,140,.4); }
  .spill.bad { color:var(--bad); border-color:rgba(201,97,87,.4); }
  .spill.warn { color:var(--warn); border-color:rgba(194,154,85,.4); }
  .spill.dim { color:var(--faint); border-color:var(--line); }
  .spill.src { color:var(--src); border-color:rgba(180,156,116,.35); }

  /* ---------- 双栏：最近运行 / 队列 ---------- */
  .duo { display:grid; grid-template-columns:1fr 1.25fr; gap:36px; }
  @media (max-width:940px) { .duo { grid-template-columns:1fr; } }
  .runline { display:flex; align-items:baseline; gap:10px; flex-wrap:wrap; }

  /* ---------- 页脚 ---------- */
  .footer { position:relative; z-index:2; text-align:center; padding:30px 0 26px;
    border-top:1px solid var(--line); font:11px/1 var(--mono); color:var(--faint); letter-spacing:2px; }

  /* ---------- 输入（设置用） ---------- */
  .input { width:100%; background:var(--bg2); border:1px solid var(--line); border-radius:2px;
    padding:9px 12px; color:var(--txt); font:13px/1.5 var(--sans); outline:none;
    transition:border-color .15s; }
  .input:focus { border-color:var(--line2); }
  .input::placeholder { color:var(--faint); }
  .input:disabled { opacity:.4; }
  .input.mono { font:12px/1.7 var(--mono); }

  /* ---------- 登录门 ---------- */
  .gate { position:fixed; inset:0; z-index:100; display:flex; align-items:center; justify-content:center;
    background:rgba(22,20,17,.94); backdrop-filter:blur(3px);
    transition:opacity .3s ease, visibility .3s; }
  .gate.gate-hide { opacity:0; visibility:hidden; pointer-events:none; }
  .gate-card { width:min(400px,90vw); padding:14px 6px; text-align:center; }
  .gate-card .wm { font:700 44px/1 var(--serif); letter-spacing:1px; }
  .gate-card .wm i { font-style:normal; color:var(--accent); }
  .gate-card h1 { font:600 22px/1.4 var(--serif); margin:20px 0 8px; }
  .gate-sub { color:var(--dim); font-size:13px; line-height:1.8; margin:0 0 22px; }
  .qr-img img { width:190px; height:190px; margin:16px auto 0; display:block;
    border:1px solid var(--line); padding:8px; background:#fff; }
  .qr-tip { font:12px/1.7 var(--mono); color:var(--dim); margin-top:14px; min-height:18px; letter-spacing:.5px; }
  .link-btn { background:none; border:0; cursor:pointer; font:12px/1 var(--mono); color:var(--faint);
    margin-top:24px; letter-spacing:1px; }
  .link-btn:hover { color:var(--txt); }

  /* ---------- 设置弹窗 ---------- */
  .modal { position:fixed; inset:0; z-index:90; background:rgba(16,14,12,.78);
    display:flex; align-items:center; justify-content:center; animation:fadeIn .18s ease; }
  @keyframes fadeIn { from { opacity:0; } }
  .modal-content { width:min(680px,94vw); max-height:88vh; overflow:auto;
    background:var(--bg2); border:1px solid var(--line2); padding:30px 34px;
    animation:fadeUp .22s ease; }
  @keyframes fadeUp { from { opacity:0; transform:translateY(8px); } }
  .modal-head { display:flex; justify-content:space-between; align-items:baseline; margin-bottom:8px; }
  .modal-head h2 { margin:0; font:600 24px/1.2 var(--serif); }
  .cfg-sep { font:11px/1 var(--mono); color:var(--accent); letter-spacing:2.5px;
    margin:26px 0 14px; padding-bottom:8px; border-bottom:1px solid var(--line); }
  .cfg-sep:first-of-type { margin-top:10px; }
  .cfg-group { display:flex; flex-direction:column; gap:6px; flex:1; min-width:120px; margin-bottom:12px; }
  .cfg-group label { font:12px/1 var(--mono); color:var(--dim); letter-spacing:.5px; }
  .cfg-row { display:flex; gap:14px; align-items:flex-end; flex-wrap:wrap; }
  .cfg-cb { font-size:13px; display:flex; align-items:center; gap:8px; cursor:pointer;
    padding:8px 0; user-select:none; color:var(--txt); }
  .cfg-cb input[type=checkbox] { width:14px; height:14px; accent-color:var(--accent); cursor:pointer; }
  .adv { margin-top:18px; }
  .adv summary { cursor:pointer; font:12px/1 var(--mono); color:var(--dim); letter-spacing:1px; }
  .adv summary:hover { color:var(--txt); }
  textarea.input.mono { height:200px; margin-top:10px; resize:vertical; }
  .bar { display:flex; gap:10px; align-items:center; flex-wrap:wrap; margin-top:24px; }

  /* ---------- Toast ---------- */
  #toasts { position:fixed; right:24px; bottom:24px; z-index:200;
    display:flex; flex-direction:column; gap:8px; }
  .toast { background:var(--bg3); border:1px solid var(--line2); border-left:2px solid var(--accent);
    padding:11px 16px; font-size:13px; box-shadow:0 14px 30px rgba(0,0,0,.45);
    animation:slideIn .2s ease; max-width:340px; }
  .toast.ok { border-left-color:var(--ok); }
  .toast.bad { border-left-color:var(--bad); }
  .toast.warn { border-left-color:var(--warn); }
  @keyframes slideIn { from { opacity:0; transform:translateX(12px); } }
</style>
</head>
<body>
<div class="grain"></div>

<div id="gate" class="gate">
  <div class="gate-card">
    <div class="wm">nsync<i>.</i></div>
    <h1>先连上网易云</h1>
    <div id="gate-body">
      <p class="gate-sub">正在检查登录状态…</p>
    </div>
    <button class="link-btn" id="gate-skip" onclick="skipGate()" style="visibility:hidden">跳过登录，先浏览 →</button>
  </div>
</div>

<header class="topbar">
  <div class="brand">
    <div class="wordmark">nsync<i>.</i></div>
    <div class="brand-sub">NETEASE → NAVIDROME</div>
  </div>
  <div class="topbar-right">
    <span id="ck-pill" class="ck"><span class="dot dot-off" id="ck-dot"></span><span id="ck-txt">检查中…</span></span>
    <span id="yt-pill" class="ck"><span class="dot dot-warn" id="yt-dot"></span><span id="yt-txt">YouTube —</span><button class="txt-btn" onclick="checkYoutubeCookie()">验证</button></span>
    <div class="top-actions">
      <button class="txt-btn hide" id="login-btn" onclick="openGate()">登录</button>
      <button class="txt-btn" onclick="showConfig()">设置</button>
    </div>
  </div>
</header>

<div class="shell">
  <aside class="rail">
    <nav>
      <a href="#overview">总览</a>
      <a href="#search">搜索下载</a>
      <a href="#runs">运行记录</a>
      <a href="#queue">失败队列</a>
    </nav>
    <div class="rail-clock">
      <div>下次运行</div>
      <b id="rail-next">—</b>
      <div style="margin-top:12px">上次运行</div>
      <b id="rail-last">—</b>
    </div>
  </aside>

  <main>
    <section class="intro" id="overview">
      <h1>每晚，把<em>日推</em>收进你的曲库。</h1>
      <p>nsync 每天自动拉取网易云日推与歌单，匹配、下载、写入 Navidrome，再把听过的曲子 scrobble 回网易云。这里是它的仪表盘。</p>
      <div class="statusline">
        <span id="run-badge" class="run-badge idle"><i></i>空闲</span>
        <span id="run-state" class="run-state"></span>
        <span class="faint" id="scrobble-line"></span>
      </div>
      <div class="faint num sysline" id="sysline"></div>
      <div class="actions">
        <button class="btn" id="run-btn" onclick="triggerRun()">立即运行</button>
        <button class="btn ghost" id="cleanup-btn" onclick="cleanupPlaylists()">清理过期歌单</button>
        <button class="btn ghost" id="scrobble-btn" onclick="scrobbleOnly()">仅 Scrobble（测试）</button>
        <button class="btn danger hide" id="stop-btn" onclick="stopRun()">停止</button>
        <button class="btn ghost" id="refresh-btn" onclick="toggleRefresh()">暂停自动刷新</button>
      </div>
    </section>

    <section class="stats" id="stats"></section>

    <section class="sec" id="search">
      <div class="sec-head">
        <h2><span class="no">01</span>搜索下载</h2>
        <span class="sec-tip">搜到即可一键下载入库</span>
      </div>
      <div class="search-bar">
        <input id="search-query" class="input" placeholder="歌曲、歌手…"
               onkeydown="if(event.key==='Enter')doSearch()">
        <button class="btn" onclick="doSearch()">搜索</button>
      </div>
      <div id="search-status" class="search-status"></div>
      <div class="tbl-wrap"><table id="search-results"></table></div>
    </section>

    <div class="duo">
      <section class="sec" id="runs">
        <div class="sec-head"><h2><span class="no">02</span>最近运行</h2></div>
        <div class="tbl-wrap"><table id="runs-tbl"></table></div>
      </section>
      <section class="sec" id="queue">
        <div class="sec-head"><h2><span class="no">03</span>失败 / 重试队列</h2></div>
        <div class="tbl-wrap"><table id="failed"></table></div>
      </section>
    </div>

    <section class="sec">
      <div class="sec-head"><h2><span class="no">04</span>最近入库</h2></div>
      <div class="tbl-wrap"><table id="downloaded"></table></div>
    </section>
  </main>
</div>

<footer class="footer">NETEASE · NAVIDROME · LISTENBRAINZ — 仅供个人使用</footer>

<div id="toasts"></div>

<script>
const fmt = ts => ts ? new Date(ts*1000).toLocaleString('zh-CN',{hour12:false}) : '—';
let autoRefresh = true, qrTimer = null, gateDone = false;

async function api(path) { return (await fetch(path)).json(); }

async function checkYoutubeCookie() {
  const r = await (await fetch('/api/ytdlp-cookie/check', { method: 'POST' })).json();
  const type = r.state === 'valid' ? 'ok' : (r.state === 'invalid' || r.state === 'missing' ? 'bad' : 'warn');
  toast((r.message || 'YouTube Cookie 校验完成'), type);
  load();
}

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
  return `<span class="spill ${s}">${({downloaded:'已下',existed:'已有',skipped:'跳过',failed:'失败',dead:'放弃',pending:'待处理',retried:'重试'})[s]||s}</span>`;
}
function statBox(n, label, cls='') {
  return `<div class="stat ${cls}"><div class="n">${n}</div><div class="l">${label}</div></div>`;
}
function runSummary(stats) {
  let s = stats || {};
  let html = '';
  for (const k of ['downloaded','existed','skipped','failed','retried']) {
    if (s[k]) html += spill(k) + (s[k]);
  }
  if (s.duration_s) html += `<span class="faint num">${s.duration_s}s</span>`;
  if (s.cookie_ok === false) html += '<span class="spill bad">Cookie失效</span>';
  if (s.aborted) html += '<span class="spill warn">已中止</span>';
  if (s.error) html += '<span class="spill bad">错误</span>';
  if (s.scrobble?.ok && s.scrobble?.count) html += `<span class="faint num">scrobble ${s.scrobble.count} 首</span>`;
  return html || '<span class="faint">无数据</span>';
}

async function load() {
  if (!autoRefresh) return;
  let st;
  try { st = await api('/api/status'); } catch(e) { return; }

  if (!gateDone && st.cookie_ok !== true) showGateLogin();
  else if (!gateDone) closeGate();

  const ckPill = document.getElementById('ck-pill');
  const ckDot = document.getElementById('ck-dot');
  const loginBtn = document.getElementById('login-btn');
  if (st.cookie_ok) {
    ckDot.className = 'dot dot-on';
    document.getElementById('ck-txt').textContent = '网易云已登录';
    loginBtn.classList.add('hide');
  } else {
    ckDot.className = 'dot dot-off';
    document.getElementById('ck-txt').textContent = '网易云未登录';
    loginBtn.classList.remove('hide');
  }

  const badge = document.getElementById('run-badge');
  if (st.running) {
    badge.className = 'run-badge';
    badge.innerHTML = '<span class="eq"><span></span><span></span><span></span><span></span></span> 同步中';
  } else {
    badge.className = 'run-badge idle';
    badge.innerHTML = '空闲';
  }
  document.getElementById('rail-next').textContent = st.next_run || '—';
  document.getElementById('rail-last').textContent = fmt(st.last_run);
  document.getElementById('scrobble-line').innerHTML = st.scrobble ? '上次 scrobble ' + st.scrobble : '';
  const yt = st.youtube_cookie || { state:'unchecked' };
  const ytDotCls = { valid:'dot-on', invalid:'dot-off', missing:'dot-off', unknown:'dot-warn', unchecked:'dot-warn' }[yt.state] || 'dot-warn';
  const ytLabel = { valid:'YouTube 有效', invalid:'YouTube 失效', missing:'YouTube 未配置', unknown:'YouTube 未知', unchecked:'YouTube 未验证' }[yt.state] || 'YouTube 未验证';
  document.getElementById('yt-dot').className = 'dot ' + ytDotCls;
  document.getElementById('yt-txt').textContent = ytLabel;
  document.getElementById('yt-pill').title =
    [yt.message, yt.checked_at ? '上次检查 ' + fmt(yt.checked_at) : ''].filter(Boolean).join('\n');
  document.getElementById('sysline').innerHTML =
    '源链 ' + (st.dl_sources.join(' → ')) +
    ' &nbsp;·&nbsp; 推荐源 ' + (st.enabled_sources.join('、') || '无');
  document.getElementById('run-btn').disabled = st.running;
  document.getElementById('cleanup-btn').disabled = st.running;
  document.getElementById('scrobble-btn').disabled = st.running;
  document.getElementById('stop-btn').classList.toggle('hide', !st.running);
  document.getElementById('run-state').textContent = st.running ? '正在下载…' : '';

  const stats = await api('/api/stats');
  document.getElementById('stats').innerHTML =
    statBox(stats.downloaded||0,'已下载','a') +
    statBox(stats.existed||0,'已存在','b') +
    statBox(stats.failed||0,'失败','c') +
    statBox(stats.dead||0,'放弃','d') +
    statBox(stats.pending||0,'待处理','e');

  const runs = await api('/api/runs');
  document.getElementById('runs-tbl').innerHTML =
    '<tr><th>时间</th><th>结果</th></tr>' + runs.map(r =>
      `<tr><td class="faint num" style="white-space:nowrap">${fmt(r.started_at)}</td>
       <td class="runline">${runSummary(typeof r.stats==='string'?JSON.parse(r.stats||'{}'):r.stats)}</td></tr>`).join('');

  const dl = await api('/api/tracks?status=downloaded&limit=200');
  document.getElementById('downloaded').innerHTML =
    '<tr><th>曲目</th><th>歌单</th><th>来源</th></tr>' + dl.map(t =>
      `<tr><td><span class="t">${t.title}</span><br><span class="a">${t.artists.join('/')}</span></td>
       <td class="muted">${t.playlist||'—'}</td>
       <td><span class="tag">${t.download_source}</span></td></tr>`).join('');

  const failed = await api('/api/tracks?status=failed&limit=200');
  const dead = await api('/api/tracks?status=dead&limit=50');
  document.getElementById('failed').innerHTML =
    '<tr><th>曲目</th><th>原因</th><th>次数</th><th>下次重试</th><th></th></tr>' +
    failed.concat(dead).map(t =>
      `<tr><td><span class="t">${t.title}</span><br><span class="a">${t.artists.join('/')}</span></td>
       <td class="muted">${t.fail_reason}</td><td class="num">${t.attempts}</td>
       <td class="faint num">${fmt(t.next_retry_at)}</td>
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
  } else toast(r.msg || '启动失败', 'bad');
}
async function stopRun() {
  const r = await (await fetch('/api/stop', {method:'POST'})).json();
  if (r.ok) toast('已请求中止（下一首曲目前生效）', 'warn');
  else toast(r.msg || '操作失败', 'bad');
  setTimeout(load, 2000);
}
async function cleanupPlaylists() {
  const btn = document.getElementById('cleanup-btn');
  if (btn.disabled) return;
  btn.disabled = true; btn.textContent = '清理中…';
  try {
    const r = await (await fetch('/api/cleanup-playlists', {method:'POST'})).json();
    if (r.ok) {
      toast(`已清理：Navidrome 歌单 ${r.navi_deleted||0} 个，歌单文件 ${r.files_deleted||0} 个（音频保留）`, 'ok');
    } else toast(r.msg || '清理失败', 'bad');
  } catch(e) {
    toast('清理请求失败', 'bad');
  } finally {
    btn.disabled = false; btn.textContent = '清理过期歌单';
  }
  setTimeout(load, 500);
}
async function scrobbleOnly() {
  const btn = document.getElementById('scrobble-btn');
  if (btn.disabled) return;
  btn.disabled = true; btn.textContent = 'Scrobble 中…';
  try {
    const r = await (await fetch('/api/scrobble', {method:'POST'})).json();
    if (r.ok) {
      toast(`Scrobble 完成：成功 ${r.count||0} 首，失败 ${r.fail||0} 首（共 ${r.total||0} 条）`, r.fail ? 'warn' : 'ok');
    } else toast(r.msg || 'Scrobble 失败', 'bad');
  } catch(e) {
    toast('Scrobble 请求失败', 'bad');
  } finally {
    btn.disabled = false; btn.textContent = '仅 Scrobble（测试）';
  }
  setTimeout(load, 500);
}
function toggleRefresh() {
  autoRefresh = !autoRefresh;
  const btn = document.getElementById('refresh-btn');
  btn.textContent = autoRefresh ? '暂停自动刷新' : '恢复自动刷新';
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
  tip.textContent = '生成二维码…';
  const r = await (await fetch('/api/qr/start')).json();
  if (!r.ok) { tip.innerHTML = '<span class="bad">'+r.msg+'</span>'; return; }
  document.getElementById('qr-img').innerHTML = '<img src="'+r.qrimg+'" alt="二维码">';
  tip.textContent = '请用 网易云音乐 App 扫码';
  if (qrTimer) clearInterval(qrTimer);
  qrTimer = setInterval(() => qrPoll(r.key), 2000);
}
async function qrPoll(key) {
  const r = await (await fetch('/api/qr/poll?key='+encodeURIComponent(key))).json();
  const tip = document.getElementById('qr-tip');
  if (!tip) { clearInterval(qrTimer); qrTimer = null; return; }
  if (r.status === 801) tip.textContent = '等待扫码…';
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
  } else tip.innerHTML = '<span class="bad">扫码不可用 ('+r.status+')</span>';
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
  status.textContent = '找到 ' + r.length + ' 首';
  document.getElementById('search-results').innerHTML =
    '<tr><th>曲名</th><th>歌手</th><th>专辑</th><th></th></tr>' +
    r.map(s => {
      const artists = s.artists.join('/');
      return `<tr><td class="t">${s.name}</td><td class="muted">${artists}</td><td class="muted">${s.album||'—'}</td>
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
    <div class="modal-head"><h2>设置</h2><button class="txt-btn" onclick="hideModal()">关闭 ✕</button></div>
    <div class="cfg-sep">NAVIDROME 查重</div>
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
    <div class="cfg-row">
      <div class="cfg-group"><label>每日发现限额（LB+LastFM 合并，日推不限）</label>
        <input id="c-lim" class="input" style="width:90px" type="number" min="1"></div>
    </div>
    <div class="cfg-sep">下载</div>
    <div class="cfg-row" style="flex-wrap:wrap" id="c-dl-srcs"></div>
    <div class="cfg-row">
      <div class="cfg-group"><label>匹配阈值</label><input id="c-th" class="input" style="width:90px" type="number"></div>
      <div class="cfg-group"><label>时长差(秒)</label><input id="c-dur" class="input" style="width:90px" type="number"></div>
      <div class="cfg-group"><label>下载间隔(秒)</label><input id="c-int" class="input" style="width:90px" type="number"></div>
    </div>
    <div class="cfg-sep">调度</div>
    <div class="cfg-group" style="max-width:280px"><label>CRON 表达式</label><input id="c-cron" class="input mono" placeholder="30 4 * * *"></div>
    <details class="adv"><summary>高级 — 完整 YAML</summary>
      <textarea id="c-yaml" class="input mono"></textarea>
    </details>
    <div class="bar">
      <button class="btn" onclick="saveConfig()">保存</button>
      <button class="btn ghost" onclick="hideModal()">取消</button>
      <span id="cfg-st" class="faint"></span>
    </div>`;
  showModal(html);
  document.getElementById('cfg-st').textContent = '加载中…';
  fetch('/api/config').then(r => r.json().catch(() => ({ok:false, msg:'HTTP '+r.status+'（响应非 JSON）'}))).then(r => {
    if (!r.ok) { document.getElementById('cfg-st').textContent = '加载失败: '+(r.msg||r.detail||'未知错误'); return; }
    const y = (r.data && typeof r.data === 'object') ? r.data : {};
    document.getElementById('c-yaml').value = r.raw || '';
    try {
      const srcs = ['ytdlp','netease','kuwo','migu','bodian','qq','kugou','qianqian'];
      const dlSrcs = Array.isArray(y.download?.sources) ? y.download.sources : [];
      document.getElementById('c-dl-srcs').innerHTML = srcs.map(s =>
        `<label class="cfg-cb"><input type="checkbox" value="${s}" ${dlSrcs.includes(s)?'checked':''}> ${s}</label>`
      ).join('');
      setVal('c-nav-url', y.navidrome?.url); setVal('c-nav-user', y.navidrome?.username); setVal('c-nav-pass', y.navidrome?.password);
      setCb('c-lb-en', y.sources?.listenbrainz?.enabled);
      setVal('c-lb-un', y.sources?.listenbrainz?.username);
      cfgToggle('c-lb-un');
      setCb('c-lf-en', y.sources?.lastfm?.enabled);
      setVal('c-lf-k', y.sources?.lastfm?.api_key); setVal('c-lf-u', y.sources?.lastfm?.username);
      cfgToggle('c-lf-k'); cfgToggle('c-lf-u');
      setCb('c-dd-en', y.sources?.netease_daily?.enabled); setCb('c-pl-en', y.sources?.netease_playlists?.enabled);
      setVal('c-th', y.download?.title_threshold); setVal('c-dur', y.download?.max_duration_diff);
      setVal('c-int', y.download?.interval_seconds); setVal('c-cron', y.schedule?.cron);
      setVal('c-lim', y.daily_discover_limit);
    } catch (e) {
      document.getElementById('cfg-st').textContent = '表单回显失败: '+e;
      return;
    }
    document.getElementById('cfg-st').textContent = '';
  }).catch(e => {
    document.getElementById('cfg-st').textContent = '加载失败: '+e;
  });
}
function cfgToggle(id) { document.getElementById(id).disabled = !document.getElementById(id.replace('-k','-en').replace('-u','-en')).checked; }
function setVal(id, v) { const e=document.getElementById(id); if(e && v!==undefined) e.value=v; }
function setCb(id, v) { const e=document.getElementById(id); if(e) e.checked=!!v; }
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
    daily_discover_limit: Math.max(1, parseInt(v('c-lim'))||10),
    schedule: {cron: v('c-cron')||'30 4 * * *'},
  };
  const r = await (await fetch('/api/config', {method:'PUT', headers:{'Content-Type':'application/json'}, body: JSON.stringify(body)})).json();
  if (r.ok) { toast('配置已保存并热生效', 'ok'); hideModal(); load(); }
  else toast('保存失败: '+(r.msg||''), 'bad');
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
            "youtube_cookie": jobs.youtube_cookie_status,
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

    @app.post("/api/cleanup-playlists")
    def cleanup_playlists():
        """手动清理过期自动歌单（Navidrome + 本地 m3u8 + 数据库关联），
        不触发完整每日同步。音频文件不受影响。"""
        if jobs._lock.locked():
            return JSONResponse({"ok": False, "msg": "任务正在运行中，请结束后再清理"},
                                status_code=409)
        try:
            stats = jobs._cleanup_old_playlists() or {}
            return {"ok": True, **stats}
        except Exception as e:
            log.warning("手动清理歌单异常: %s", e, exc_info=True)
            return {"ok": False, "msg": str(e)}

    @app.post("/api/scrobble")
    def scrobble_recent():
        """测试入口：仅执行 ListenBrainz → 网易云听歌回传，
        不触发下载/建单。执行期间持有任务锁，防止与每日任务或
        重复点击并发 scrobble（并发会导致网易云重复计数）。"""
        if not jobs._lock.acquire(blocking=False):
            return JSONResponse({"ok": False, "msg": "任务正在运行中，请结束后再试"},
                                 status_code=409)
        try:
            jobs.refresh_cookie_status()
            stats = jobs._scrobble_recent() or {}
            return {"ok": True, **stats}
        except Exception as e:
            log.warning("手动 scrobble 异常: %s", e, exc_info=True)
            return {"ok": False, "msg": str(e)}
        finally:
            jobs._lock.release()

    @app.post("/api/ytdlp-cookie/check")
    def check_ytdlp_cookie():
        """手动验证 YouTube Cookie，不返回 Cookie 内容。"""
        try:
            return jobs.refresh_youtube_cookie_status()
        except Exception as e:
            log.warning("YouTube Cookie 校验异常: %s", type(e).__name__)
            return {"state": "unknown", "ok": None, "message": "校验异常"}

    @app.post("/api/retry/{track_id}")
    def retry(track_id: int):
        db.reset_retry(track_id)
        return {"ok": True}

    @app.get("/api/config")
    def get_config():
        """返回已解析的配置（raw=原始 YAML 文本），供设置页回显。

        不能用 JSONResponse 包原始文本：会被整体 JSON 转义成一行，
        前端无法按行解析。"""
        try:
            raw_text = cfg._path.read_text(encoding="utf-8")
            data = yaml.safe_load(raw_text)
            if not isinstance(data, dict):
                data = {}
            # yaml 可能解析出 datetime.date 等非 JSON 类型，统一转字符串，
            # 避免 JSON 序列化抛错导致 500、前端卡在"加载中"。
            try:
                data = json.loads(json.dumps(data, default=str, ensure_ascii=False))
            except Exception:
                data = {}
            return {"ok": True, "raw": raw_text, "data": data}
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
            old_ytdlp_cookie_file = cfg.ytdlp_cookies_file
            for at in ("music_dir","data_dir","ncm_api_url","cron","daily_discover_limit",
                       "playlist_retention_days",
                       "dl_sources","dl_interval","ytdlp_cookies_file",
                       "title_threshold","max_duration_diff","run_on_startup",
                       "web_host","web_port","web_auth_user","web_auth_password"):
                setattr(cfg, at, getattr(new_cfg, at))
            cfg.navidrome = new_cfg.navidrome
            cfg.sources = new_cfg.sources
            if cfg.netease_cookie != new_cfg.netease_cookie:
                cfg.netease_cookie = new_cfg.netease_cookie
                jobs.set_cookie(cfg.netease_cookie)
            if cfg.ytdlp_cookies_file != old_ytdlp_cookie_file:
                jobs.youtube_cookie_status = {
                    "state": "unchecked", "ok": None, "message": "尚未验证", "checked_at": None,
                }
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
