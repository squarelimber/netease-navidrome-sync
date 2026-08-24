# netease-navidrome-sync

一个配合 [Navidrome](https://www.navidrome.org) 使用的曲库辅助工具。

每日自动聚合 **网易云日推 / ListenBrainz / Last.fm** 的推荐，
通过 [musicdl](https://github.com/CharlesPikachu/musicdl) 多平台下载引擎与
[yt-dlp](https://github.com/yt-dlp/yt-dlp) YouTube 源匹配下载，
内嵌标签/封面/歌词，写入 Navidrome 音乐目录，文件系统监听 + m3u8 自动入库。

```
Navidrome 播放 ──scrobble──> ListenBrainz / Last.fm
                                  │ 产生推荐
                                  ▼
        本工具每日拉取推荐 ──> 匹配下载(musicdl) ──> 打标签写盘
                                  │
                                  ▼
        写入音乐目录 + 生成 .m3u8 ──> Navidrome 自动扫描入库
```

## 功能

- **三源推荐聚合**：网易云每日推荐（30 首/天）、ListenBrainz 协同过滤 + 官方每周歌单、Last.fm 常听/最爱的相似曲目
- **指定网易云歌单同步**：持续同步"我喜欢的音乐"等歌单到 Navidrome
- **多源下载链**：基于 [musicdl](https://github.com/CharlesPikachu/musicdl) 的多平台下载（网易云→酷我→咪咕→波点→QQ），单源失败自动降级；`ytdlp` YouTube 源默认置于源链首位，各平台无源时仍可继续尝试
- **YouTube 双模式格式探测**：对同一候选视频分别探测匿名模式和 Cookie 模式的可用格式，优先选择可直接入库的 `m4a`，其次 `mp4`/`aac`；下载失败会尝试另一种模式
- **繁简自动归一**：匹配与去重前自动将繁体转为简体（opencc），繁体歌单/曲库元数据不再失配
- **网易云扫码登录**：状态页点"显示二维码"用 App 扫码登录，自动注入 Cookie
- **搜索下载**：状态页搜索歌手/歌名，一键下载
- **自动匹配校验**：归一化（含繁简转换）+ 模糊比对（标题/歌手/时长），避免 Cover 版误下
- **完整元数据**：内嵌 ID3/FLAC/M4A 标签、封面、歌词，写 `.lrc` 旁挂文件
- **查重不重复**：调用 Navidrome 的 Subsonic `search3` 接口检测曲库已有曲目
- **听歌回传**：每日自动将 ListenBrainz 的新播放记录回传到网易云（听歌排行 + 最近播放）；weapi 直连 `music.163.com`，绕开 ncm-api 的 `clientlog3` 日志域名
- **失败重试队列**：匹配/下载失败自动入队，按退避策略每日重试
- **轻量状态页**：Cookie 健康、统计、运行历史、失败队列，可暂停刷新、中止任务、逐条重试
- **滚动日志**：日志按天午夜滚动，保留最近 14 个历史文件
- **Docker 一键部署**：两个容器（ncm-api + 本工具），共享音乐目录

## 系统要求

- Navidrome 实例（用于查重 + 接收新文件，不与本工具同机也可）
- **Docker**（必需，因依赖 ncm-api 容器处理网易云 API）
- 网易云账号
- 可选：ListenBrainz 账号、Last.fm API Key

## 安装方式

### 方式 A：通过 GitHub 网页下载

1. 打开仓库页面 <https://github.com/squarelimber/netease-navidrome-sync> → **Code → Download ZIP**
2. 解压并进入目录：
   ```bash
   unzip netease-navidrome-sync-main.zip
   cd netease-navidrome-sync-main
   ```
3. 配置：
   ```bash
   cp config.example.yaml config.yaml
   # 编辑 config.yaml：修改音乐目录路径等
   ```
4. 修改 `docker-compose.yml` 里的 **`/path/to/your/music`** 为你的真实音乐目录（与 Navidrome 挂载的**同一目录**）；ncm-api 会暴露 `8679` 端口供调试用（内部通信走 Docker 网络不受影响）
5. 构建并启动：
   ```bash
   docker compose up -d --build
   ```
6. 打开状态页 `http://你的IP:8678` → 点"显示二维码"用网易云 App 扫码登录

> 后续更新只需 `git pull && docker compose restart navidrome-sync`，.py 文件已热挂载，无需 rebuild。

> 镜像会在构建阶段安装 Deno，供 yt-dlp 的 YouTube 提取使用；如果构建环境无法访问 GitHub，需要为 Docker 配置可用的网络代理或 Deno 发布镜像。

> **国内网络加速构建**：如果 pip 下载慢，可加 `--build-arg` 指定镜像源：
> `docker compose build --build-arg PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple navidrome-sync`
> （本镜像不依赖 apt/ffmpeg；构建阶段还会下载 Deno，网络质量会同时影响 pip 和 Deno 下载）

### 方式 B：用 git 克隆

```bash
git clone https://github.com/squarelimber/netease-navidrome-sync.git
cd netease-navidrome-sync
cp config.example.yaml config.yaml
# 编辑 config.yaml、docker-compose.yml
docker compose up -d --build
```

## 配置说明

| 字段 | 说明 |
|---|---|
| `music_dir` | 容器内音乐目录，与 Navidrome 挂载的同一目录（默认 `/music`） |
| `ncm_api_url` | ncm-api 容器地址，Docker 环境下保持 `http://ncm-api:3000` |
| `navidrome.url/username/password` | Navidrome 地址与账号，用于查重 |
| `netease.cookie_file` | Cookie 持久化路径（扫码登录后自动写入） |
| `sources.netease_daily.enabled` | 启用网易云日推 |
| `sources.netease_playlists.playlists` | 要同步的歌单列表 |
| `sources.listenbrainz.username` | ListenBrainz 用户名 |
| `sources.lastfm` | Last.fm API Key + 用户名 |
| `download.sources` | 下载源链顺序，默认 `ytdlp` 优先（YouTube 兼容性好，优先直取音频格式，无需 ffmpeg），musicdl 各源作后备 |
| `download.ytdlp_cookies_file` | YouTube Cookie 文件路径（Netscape 格式）；存在时会与匿名模式并行探测格式，状态页可手动验证 |
| `discover_daily_limit` | 每日新增推荐曲上限 |
| `playlist_retention_days` | 自动推荐歌单保留天数，默认 3 天（包含今天）；只删除旧 `.m3u8` 和数据库关联，不删除音频文件 |
| `schedule.cron` | 每日任务时间，默认 `30 4 * * *` |
| `web.port` | 状态页端口，默认 8678 |
| `web.auth_user/auth_password` | 可选：状态页 Basic Auth（留空则不启用） |

### 获取网易云 Cookie（备选）

如果扫码登录不可用，可以手动抓取：
1. 浏览器登录 <https://music.163.com> → F12 → Network
2. 刷新页面，点任意请求 → Request Headers → 复制 Cookie
3. 粘贴到 `data/cookie.txt`（一行，不要引号）

要求含 `MUSIC_U=...`。

### YouTube 下载与 Cookie

`yt-dlp` 的 YouTube 流会因视频、出口网络、登录态和客户端类型不同而变化。工具不会固定只使用某一种客户端，而是按以下流程选择：

1. 使用已配置的 YouTube Cookie 搜索候选；搜索失败且存在 Cookie 时，再用匿名模式搜索。
2. 对选中的视频分别执行匿名/Cookie 两次格式探测。
3. 只接受带直链的音频-only 格式（无视频轨），优先级为 `m4a` > `mp4` > `aac`；同一格式优先普通 HTTP/HTTPS 直链和较高码率，完全相同则优先 Cookie 模式。
4. 下载指定的格式 ID；如果该模式下载失败，会按探测结果尝试另一模式，最后再交给后续下载源。

Cookie 模式探测不到任何可用音频格式时（通常意味着 Cookie 已失效或账号被风控——被风控账号带 Cookie 访问时返回的格式列表反而更差），程序会直接判定 ytdlp 源本次不可用并跳过匿名回退下载（匿名下载此时大概率 403，回退只会白烧请求并污染 403 熔断计数），交给后续下载源。未配置 Cookie 时不受此限制，匿名模式照常工作。日志中会记录 `mode=anonymous/cookie`、格式 ID 和码率，便于排查 403/503。

YouTube Cookie 文件必须是 Netscape/Mozilla 格式（通常由已登录的普通浏览器配置导出），不要使用无痕窗口临时会话或把 Cookie 粘贴到公开位置。状态页的“验证 YouTube Cookie”会访问需要登录的历史记录页，并返回三种状态：

- **有效**：探测成功；
- **明确失效**：检测到登录态失效或需要登录；
- **暂时无法判断**：网络 403/429、机器人验证、PO Token 或超时等情况。此状态不等同于 Cookie 已失效。

### 获取歌单 ID

网页版打开歌单 → 地址栏 `?id=` 后面的数字。

### 获取 Last.fm API Key

<https://www.last.fm/api/account/create>，只需 API Key，不要 Secret。

## 闭环节奏建议

Navidrome 设置中开启 ListenBrainz / Last.fm scrobble：

```
你听歌 → Navidrome scrobble → ListenBrainz
                                 ├── 平台生成推荐 → 工具次日拉取下载
                                 └── 工具每日回传 → 网易云听歌排行
```

本工具每日同步时，会自动从 ListenBrainz 读取新播放记录，匹配网易云曲目后调用 `/scrobble` 回传到网易云，保持听歌排行和最近播放同步。

## 目录结构（运行后）

```
music/
├── Discover/                      # 推荐曲目 + 手动搜索下载
│   ├── 歌手 - 歌名.mp3
│   ├── 歌手 - 歌名.lrc
│   └── 网易云日推-2026-07-20.m3u8
└── NetEase/
    └── 歌单名/                     # 同步的网易云歌单
        ├── 歌手 - 歌名.mp3
        └── 歌单名.m3u8
```

## 状态页

- **登录门**：打开页面未登录时先显示扫码登录，扫码成功自动进入管理页（可跳过）
- 网易云 Cookie 状态 ✓/✗，失效时可随时重新登录
- YouTube Cookie 状态：可手动验证，并区分有效、明确失效与暂时无法判断
- 下载源链、推荐源列表、听歌同步状态
- 四类曲目统计（已下载/已存在/失败/待处理）
- 搜索下载（搜索歌手/歌名一键下载）
- **配置编辑器 ⚙**：点击 ⚙ 打开表单编辑 Navidrome/推荐源/下载等关键项，保存后热重载；Cookie 变更自动校验
- 最近运行记录（已下/跳过/失败数量 + 耗时）
- 最近入库列表（可滚动）
- 失败/重试队列（可滚动），逐条重试
- 停止任务 / 暂停自动刷新

## 运行与排错

```bash
# 立即跑一次每日任务
docker compose exec navidrome-sync python -m app.main --run-now

# 看日志
docker compose logs -f navidrome-sync

# 查看文件日志（当前日志 + 最近 14 个按天滚动的历史日志）
ls data/logs

# 修改代码后热重载（无需 rebuild）
docker compose restart navidrome-sync
```

常见问题：

- **网易云 Cookie 无效**：状态页重新扫码登录
- **旧推荐歌单**：每天任务完成后自动清理超过 `playlist_retention_days` 的网易云日推、ListenBrainz CF 和 Last.fm 推荐 `.m3u8`；固定歌单和音频文件不会删除
- **网易云听歌回传全部失败（502/405/403）**：Cookie 校验成功不代表 `/scrobble` 上游可用。回传**优先直连 `music.163.com/api/feedback/weblog`（weapi 加密）**，绕开 ncm-api 转发的 `clientlog3.music.163.com`（该日志域名常被 403/TLS 拒连，是 NAS 上回传全挂的常见根因）；仅当无 Cookie 或 pycryptodome 缺失时才回退到 ncm-api `/scrobble`。回传已按 2 秒限速并对临时 502/频控响应自动重试。若直连仍失败，检查容器到 `music.163.com` 的出站网络；若走 ncm-api 兜底，再检查其 `HTTP_PROXY/HTTPS_PROXY` 代理与 TLS 连接
- **YouTube Cookie 无效**：重新导出 Netscape 格式 Cookie；403 或风控错误会显示为“无法判断”，不会直接误报失效
- **yt-dlp 报 403/503 或没有 m4a**：先看日志中的两次格式探测结果；程序会比较匿名/Cookie 模式，并自动尝试 `m4a`、`mp4`、`aac` 中实际可用的音频格式。两种模式都没有直链时才会切换到 musicdl 后备源
- **某首歌一直失败**：VIP 曲目且各平台均无免费音源，标记为 `dead`
- **Navidrome 没扫到新文件**：确认 `Scanner.WatcherWait` 未被关闭

## 架构

```
状态页 ←── Python 工具 ──HTTP──→ ncm-api (Node.js) ──weapi──→ 网易云
                │                         ↑
                │                    Docker 容器
                │                    (moefurina/ncm-api)
                ├──→ weapi 直连 ──→ music.163.com/api/feedback/weblog（听歌回传，优先）
                ↓
          yt-dlp（匿名/Cookie 双模式格式探测）
             └──→ YouTube 音频直链（m4a/mp4/aac）
          musicdl 多源下载链 ──→ 网易云/酷我/咪咕/波点/QQ
```

## 法律与合规

仅供个人学习与自建曲库使用。下载行为依赖于第三方平台的非公开接口，可能违反其服务条款。使用者自行承担相关风险。

## 致谢

- [musicdl](https://github.com/CharlesPikachu/musicdl) — 多平台音乐下载库
- [Navidrome](https://github.com/navidrome/navidrome) — 开源音乐服务器
- [api-enhanced](https://github.com/NeteaseCloudMusicApiEnhanced/api-enhanced) — 网易云 API 后端
- [ListenBrainz](https://listenbrainz.org) / [Last.fm](https://www.last.fm) — 推荐数据来源
