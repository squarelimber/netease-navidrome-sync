"""状态页：FastAPI 单页应用 + JSON API。"""

import json
import logging
import threading

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
  .tab-btn { background:transparent; color:var(--muted); border:0; padding:8px 20px;
             font-size:13px; cursor:pointer; border-bottom:2px solid transparent; margin-bottom:-1px; }
  .tab-btn.active { color:#fff; border-bottom-color:var(--accent); }
  .tab-btn:hover:not(.active) { color:#aabbdd; }
  .modal { position:fixed; inset:0; background:rgba(0,0,0,.6); display:flex; align-items:center; justify-content:center; z-index:99; }
  .modal-content { background:var(--card); border:1px solid var(--line); border-radius:var(--radius); padding:24px; max-width:700px; width:90%; max-height:80vh; }
  .modal textarea { background:#0b1020; border:1px solid var(--line); border-radius:8px; color:#dfe6f0; font-family:monospace; font-size:13px; padding:12px; width:100%; height:50vh; resize:vertical; }
  .cfg-group { display:flex; flex-direction:column; gap:3px; flex:1; min-width:100px; margin-bottom:10px; }
  .cfg-group label { font-size:12px; color:var(--muted); }
  .cfg-row { display:flex; gap:10px; align-items:flex-end; flex-wrap:wrap; }
  .cfg-sep { font-size:12px; color:#8899cc; border-bottom:1px solid var(--line); padding:12px 0 4px; margin:6px 0 10px; text-transform:uppercase; letter-spacing:1px; }
  .cfg-cb { font-size:13px; display:flex; align-items:center; gap:6px; cursor:pointer; }
  .cfg-cb input[type=checkbox] { width:16px; height:16px; }
</style>
</head>
<body>
<h1>🎵 <span>Navidrome Sync</span>
  <span onclick="showConfig()" style="font-size:16px;cursor:pointer;color:var(--muted);margin-left:10px" title="配置">⚙</span>
</h1>
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
    <h2>网易云扫码登录</h2>
    <div class="qr-box">
      <button onclick="qrStart()">显示二维码</button>
      <div id="qr-img"></div>
      <div class="qr-tip" id="qr-tip"></div>
    </div>
  </div>
</div>

<div class="card" style="margin-top:16px">
  <div style="display:flex;gap:0;border-bottom:1px solid var(--line);margin-bottom:14px">
    <button id="stab-search" class="tab-btn active" onclick="switchSearchTab('search')">搜索</button>
    <button id="stab-rank" class="tab-btn" onclick="switchSearchTab('rank')">排行榜</button>
  </div>
  <div id="stab-search-content">
    <div style="display:flex;gap:8px;margin-bottom:10px">
      <input id="search-query" class="input" placeholder="搜歌曲、歌手…" style="flex:1" onkeydown="if(event.key==='Enter')doSearch()">
      <button onclick="doSearch()" style="flex:0 0 auto">搜索</button>
    </div>
  </div>
  <div id="stab-rank-content" class="hide">
    <div style="display:flex;gap:6px;flex-wrap:wrap;margin-bottom:10px" id="chart-btns"></div>
  </div>
  <div id="search-status" class="muted" style="font-size:12px"></div>
  <div class="scroll" style="max-height:420px"><table id="search-results"></table></div>
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
    <div>听歌同步：${st.scrobble || '<span class="muted">-</span>'}</div>
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
  document.getElementById('qr-img').innerHTML = '<img src="'+r.qrimg+'" alt="二维码">';
  document.getElementById('qr-tip').innerHTML = '请用 <b>网易云音乐 App</b> 扫码';
  if (qrTimer) clearInterval(qrTimer);
  qrTimer = setInterval(() => qrPoll(r.key), 2000);
}
async function qrPoll(key) {
  const r = await (await fetch('/api/qr/poll?key='+encodeURIComponent(key))).json();
  const tip = document.getElementById('qr-tip');
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
var searchTimer = null;
async function doSearch() {
  const q = document.getElementById('search-query').value.trim();
  if (!q) return;
  const status = document.getElementById('search-status');
  status.textContent = '搜索中…';
  const r = await (await fetch('/api/search?q='+encodeURIComponent(q)+'&limit=30')).json();
  if (r.error) { status.innerHTML = '<span class="bad">'+r.error+'</span>'; return; }
  if (!r.length) { status.innerHTML = '无结果'; document.getElementById('search-results').innerHTML = ''; return; }
  status.innerHTML = '找到 '+r.length+' 首';
  document.getElementById('search-results').innerHTML =
    '<tr><th>曲名</th><th>歌手</th><th>专辑</th><th></th></tr>' +
    r.map(s => {
      const artists = s.artists.join('/');
      return `<tr><td>${s.name}</td><td class="muted">${artists}</td><td class="muted">${s.album||'-'}</td>
        <td><button class="small" onclick="dlSong('${encodeURIComponent(s.artists[0]||'')}','${encodeURIComponent(s.name)}')">下载</button></td></tr>`;
    }).join('');
}
async function dlSong(artist, title) {
  const status = document.getElementById('search-status');
  const a = decodeURIComponent(artist), t = decodeURIComponent(title);
  status.innerHTML = '下载中: '+a+' - '+t+' …';
  const r = await (await fetch('/api/download', {method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({artist: a, title: t})})).json();
  status.innerHTML = r.ok
    ? '<span class="ok">✓ 下载完成: '+r.file+'</span>'
    : '<span class="bad">✗ 下载失败: '+(r.msg||'')+'</span>';
  load();
}
function showConfig() {
  const html = `<div style="min-width:600px">
    <h2 style="margin-bottom:16px">配置</h2>
    <div class="cfg-group"><label>Navidrome 地址</label><input id="c-nav-url" class="input" placeholder="http://192.168.1.10:4533"></div>
    <div class="cfg-row"><div class="cfg-group"><label>用户名</label><input id="c-nav-user" class="input"></div>
      <div class="cfg-group"><label>密码</label><input id="c-nav-pass" class="input" type="password"></div></div>

    <div class="cfg-sep">推荐源</div>
    <div class="cfg-row"><label class="cfg-cb"><input type="checkbox" id="c-lb-en" onchange="cfgToggle('c-lb-un')"> ListenBrainz</label><input id="c-lb-un" class="input" placeholder="用户名" style="width:200px" disabled></div>
    <div class="cfg-row"><label class="cfg-cb"><input type="checkbox" id="c-lf-en" onchange="cfgToggle('c-lf-k');cfgToggle('c-lf-u')"> Last.fm</label><input id="c-lf-k" class="input" placeholder="API Key" style="width:200px" disabled><input id="c-lf-u" class="input" placeholder="用户名" style="width:160px" disabled></div>
    <div class="cfg-row"><label class="cfg-cb"><input type="checkbox" id="c-dd-en"> 网易云日推</label>
      <label class="cfg-cb"><input type="checkbox" id="c-pl-en"> 网易云歌单同步</label></div>

    <div class="cfg-sep">下载</div>
    <div class="cfg-row" style="flex-wrap:wrap" id="c-dl-srcs"></div>
    <div class="cfg-row"><div class="cfg-group"><label>匹配阈值</label><input id="c-th" class="input" style="width:80px" type="number"></div>
      <div class="cfg-group"><label>时长差(秒)</label><input id="c-dur" class="input" style="width:80px" type="number"></div>
      <div class="cfg-group"><label>下载间隔(秒)</label><input id="c-int" class="input" style="width:80px" type="number"></div></div>

    <div class="cfg-sep">调度</div>
    <div class="cfg-row"><div class="cfg-group"><label>Cron</label><input id="c-cron" class="input" style="width:300px" placeholder="30 4 * * *"></div></div>

    <details style="margin-top:14px"><summary style="cursor:pointer;font-size:13px;color:var(--muted)">高级 → 完整 YAML</summary>
      <textarea id="c-yaml" class="input" style="font-family:monospace;height:200px;margin-top:8px"></textarea>
    </details>

    <div class="bar" style="margin-top:14px"><button onclick="saveConfig()">保存</button><button class="secondary" onclick="hideModal()">取消</button><span id="cfg-st"></span></div>
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
    const srcs = ['netease','kuwo','migu','bodian','qq'];
    const act = (y.download?.sources || []);
    document.getElementById('c-dl-srcs').innerHTML = srcs.map(s =>
      `<label class="cfg-cb" style="margin-right:8px"><input type="checkbox" value="${s}" ${act.includes(s)?'checked':''}> ${s}</label>`
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
  const cb=n=>document.getElementById(n)?.checked||false, val=n=>document.getElementById(n)?.value||'';
  const srcs=Array.from(document.querySelectorAll('#c-dl-srcs input:checked')).map(e=>e.value);
  let y=document.getElementById('c-yaml').value;
  if(!y.trim()){
    const esc=s=>s.replace(/"/g,'\\"');
    y= `music_dir: /music
data_dir: /app/data
ncm_api_url: ${val('c-nav-url')||'http://ncm-api:3000'}
navidrome:\n  url: ${esc(val('c-nav-url'))}\n  username: ${esc(val('c-nav-user'))}\n  password: ${esc(val('c-nav-pass'))}
netease:\n  cookie_file: /app/data/cookie.txt
sources:\n  netease_daily: {enabled: ${cb('c-dd-en')}}\n  netease_playlists: {enabled: ${cb('c-pl-en')}, playlists: []}\n  listenbrainz: {enabled: ${cb('c-lb-en')}, username: ${val('c-lb-un')}}\n  lastfm: {enabled: ${cb('c-lf-en')}, api_key: ${val('c-lf-k')}, username: ${val('c-lf-u')}}
download:\n  sources: [${srcs.join(',')}]\n  interval_seconds: ${val('c-int')||2}\n  title_threshold: ${val('c-th')||85}\n  max_duration_diff: ${val('c-dur')||12}
schedule:\n  cron: ${val('c-cron')||'30 4 * * *'}\n  run_on_startup: false
web:\n  host: 0.0.0.0\n  port: 8678`.trim();
  }
  const r=await(await fetch('/api/config',{method:'PUT',headers:{'Content-Type':'text/yaml'},body:y})).json();
  document.getElementById('cfg-st').innerHTML=r.ok?'<span class="ok">✓ 已保存, 配置已热加载</span>':'<span class="bad">✗ '+r.msg+'</span>';
}
function hideModal() { const m = document.querySelector('.modal'); if(m) m.remove(); }
function showModal(html) {
  const m = document.createElement('div'); m.className='modal'; m.innerHTML='<div class="modal-content">'+html+'</div>';
  m.addEventListener('click', e => { if(e.target===m) m.remove(); });
  document.body.appendChild(m);
}
const CHARTS = [
  {id:0, name:'热歌榜'}, {id:1, name:'新歌榜'}, {id:2, name:'原创榜'},
  {id:3, name:'飙升榜'}, {id:4, name:'电音榜'}, {id:5, name:'抖音榜'},
];
function switchSearchTab(tab) {
  document.getElementById('stab-search-content').classList.toggle('hide', tab !== 'search');
  document.getElementById('stab-rank-content').classList.toggle('hide', tab !== 'rank');
  document.getElementById('stab-search').classList.toggle('active', tab === 'search');
  document.getElementById('stab-rank').classList.toggle('active', tab === 'rank');
  if (tab === 'rank' && !document.getElementById('chart-btns').children.length) {
    document.getElementById('chart-btns').innerHTML = CHARTS.map(c =>
      `<button class="small" onclick="loadChart(${c.id},'${c.name}')" style="background:var(--card)">${c.name}</button>`
    ).join('');
  }
}
async function loadChart(typeId, typeName) {
  const status = document.getElementById('search-status');
  status.textContent = '加载 '+typeName+'…';
  const r = await (await fetch('/api/chart?type='+typeId)).json();
  document.getElementById('search-results').innerHTML =
    '<tr><th>曲名</th><th>歌手</th><th>专辑</th><th></th></tr>' +
    r.map(s => {
      const a = encodeURIComponent(s.artists[0]||''), t = encodeURIComponent(s.name);
      return `<tr><td>${s.name}</td><td class="muted">${s.artists.join('/')}</td><td class="muted">${s.album||'-'}</td>
        <td><button class="small" onclick="dlSong('${a}','${t}')">下载</button></td></tr>`;
    }).join('');
  status.innerHTML = typeName+' — '+r.length+' 首';
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
            new_text = (await req.body()).decode("utf-8")
            import yaml; yaml.safe_load(new_text)
        except Exception as e:
            return {"ok": False, "msg": f"YAML 格式错误: {e}"}
        try:
            cfg._path.write_text(new_text, encoding="utf-8")
            from . import config as config_mod
            new_cfg = config_mod.load()
            for k in ("music_dir","data_dir","ncm_api_url","cron","discover_daily_limit",
                      "dl_sources","dl_interval","dl_quality","dl_sources_timeout",
                      "title_threshold","max_duration_diff","run_on_startup",
                      "web_host","web_port"):
                setattr(cfg, k, getattr(new_cfg, k))
            cfg.navidrome = new_cfg.navidrome
            cfg.sources = new_cfg.sources
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

    @app.get("/api/chart")
    def chart(type: int = 0):
        ncm = getattr(app.state, "ncm_client", None)
        if not ncm:
            return {"error": "网易云后端未连接"}
        try:
            return ncm.top_song(type, limit=100)
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
