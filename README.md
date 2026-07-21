# netease-navidrome-sync

一个配合 [Navidrome](https://www.navidrome.org) 使用的曲库辅助工具。

每日自动聚合 **网易云日推 / ListenBrainz / Last.fm** 的推荐，
匹配、下载缺失曲目，内嵌标签/封面/歌词，写入 Navidrome 音乐目录，
通过文件系统监听 + m3u8 自动入库并生成歌单。

```
Navidrome 播放 ──scrobble──> ListenBrainz / Last.fm
                                  │ 产生推荐
                                  ▼
        本工具每日拉取推荐 ──> 匹配网易云 ──> 下载打标签
                                  │
                                  ▼
        写入音乐目录 + 生成 .m3u8 ──> Navidrome 自动扫描入库
```

## 功能

- **三源推荐聚合**：网易云每日推荐（30 首/天）、ListenBrainz 协同过滤 + 官方每周歌单、Last.fm 常听/最爱的相似曲目
- **指定网易云歌单同步**：持续同步"我喜欢的音乐"等歌单到 Navidrome
- **多源下载链**：基于 [musicdl](https://github.com/CharlesPikachu/musicdl) 的多平台下载（网易云→酷我→咪咕→波点→QQ），单源失败自动降级
- **自动匹配校验**：归一化 + 模糊比对（标题/歌手/时长），避免 Cover 版误下
- **完整元数据**：内嵌 ID3/FLAC/M4A 标签、封面、歌词，并写 `.lrc` 旁挂文件
- **查重不重复**：调用 Navidrome 的 Subsonic `search3` 接口检测曲库已有曲目
- **失败重试队列**：匹配/下载失败自动入队，按退避策略每日重试
- **轻量状态页**：浏览器查看 Cookie 健康、统计、失败队列，可手动触发运行/重试
- **Docker 一键部署**：与 Navidrome 同机即可，共享音乐目录

## 系统要求

- Navidrome 实例（用于查重 + 接收新文件；不与 Navidrome 同机也可，但需保证能写入其音乐目录）
- Docker（推荐）或 Python 3.10+
- 网易云账号 Cookie（含 `MUSIC_U`）
- 可选：ListenBrainz 账号、Last.fm API Key

## 安装方式

### 方式 A：通过 GitHub 网页下载（推荐给非命令行用户）

1. 打开仓库页面 <https://github.com/squarelimber/netease-navidrome-sync>
2. 点击绿色 **`Code`** 按钮 → **`Download ZIP`**
3. 解压到你希望存放的位置：
   ```bash
   unzip netease-navidrome-sync-main.zip
   mv netease-navidrome-sync-main netease-navidrome-sync
   cd netease-navidrome-sync
   ```
4. 复制一份配置模板并编辑：
   ```bash
   cp config.example.yaml config.yaml
   ```
5. 创建数据目录并放入网易云 Cookie：
   ```bash
   mkdir -p data
   # 用浏览器 F12 从 music.163.com 请求头复制整串 Cookie，保存到：
   #   data/cookie.txt
   ```
6. 修改 `docker-compose.yml` 里 `/path/to/your/music` 为你的真实音乐目录（与 Navidrome 挂载的是**同一目录**）
7. 构建并启动：
   ```bash
   docker compose up -d --build
   ```
8. 浏览器打开状态页：`http://你的IP:8678`

> 不想用 Docker 也可以直接解压后用 Python 跑，见下方"裸 Python 运行"。

### 方式 B：用 git 克隆

```bash
git clone https://github.com/squarelimber/netease-navidrome-sync.git
cd netease-navidrome-sync
cp config.example.yaml config.yaml
# 编辑 config.yaml、docker-compose.yml，放入 data/cookie.txt
docker compose up -d --build
```

### 方式 C：裸 Python 运行（不用 Docker）

```bash
git clone https://github.com/squarelimber/netease-navidrome-sync.git
cd netease-navidrome-sync
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp config.example.yaml config.yaml
# 编辑 config.yaml：music_dir / data_dir 指向本机真实路径；其余按需填写

# 把网易云 Cookie 写入 data/cookie.txt
mkdir -p data
# （粘贴整串 Cookie 到该文件）

# 立即跑一次验证
python -m app.main --run-now

# 常驻：调度器 + 状态页
python -m app.main
# 状态页 http://127.0.0.1:8678
```

## 配置说明

编辑 `config.yaml`，关键字段：

| 字段 | 说明 |
|---|---|
| `music_dir` | 容器内音乐目录，与 Navidrome 挂载的同一目录（默认 `/music`） |
| `data_dir` | 容器内数据目录，存 SQLite / 日志 / 临时下载（默认 `/app/data`） |
| `navidrome.url/username/password` | Navidrome 访问地址与账号，用于查重（建一个低权限专用账号即可） |
| `netease.cookie_file` | 网易云 Cookie 文件路径 |
| `sources.netease_daily.enabled` | 启用网易云日推 |
| `sources.netease_playlists.playlists` | 要同步的歌单列表，如 `- name: 我喜欢的音乐` + `id: 123456` |
| `sources.listenbrainz.username` | ListenBrainz 用户名（无需 token） |
| `sources.lastfm` | Last.fm API Key + 用户名 |
| `download.sources` | 下载源链顺序 |
| `discover_daily_limit` | 每日新增推荐曲上限（歌单同步不受此限） |
| `schedule.cron` | 每日任务时间，默认 `30 4 * * *`（04:30） |
| `web.port` | 状态页端口，默认 8678 |

### 获取网易云 Cookie

1. 浏览器访问 <https://music.163.com> 并登录
2. 按 `F12` 打开开发者工具 → 切到 **Network**
3. `Ctrl+R` 刷新页面，点列表里任意一个 `music.163.com` 请求
4. 在 **Headers → Request Headers** 中找到 `Cookie`，复制右侧**整串**
5. 粘贴到 `data/cookie.txt`（一行，不要引号）

关键点：Cookie 串里要有 `MUSIC_U=...`，否则日推和完整歌单拉不到。

### 获取歌单 ID

网页版打开目标歌单（须公开），看地址栏 `?id=` 后面的数字：
```
https://music.163.com/#/playlist?id=123456789
                                 ^^^^^^^^^ 就是这个 ID
```

### 获取 Last.fm API Key

访问 <https://www.last.fm/api/account/create>，填个应用名即可秒发；只需 **API Key**，不要 Secret。

## 闭环节奏建议

为让推荐源源不断，请确保 Navidrome 会回传 scrobble：

- Navidrome 设置 → **ListenBrainz**：填用户名 + Token（在 listenbrainz.org/settings 获取）
- Navidrome 设置 → **Last.fm**：授权连接

这样你正常听歌 → 自动 scrobble → 平台生成推荐 → 本工具次日拉取下载，形成闭环。

## 目录结构（运行后）

```
music/
├── Discover/                      # 推荐曲目统一目录
│   ├── 歌手 - 歌名.mp3
│   ├── 歌手 - 歌名.lrc
│   └── 网易云日推-2026-07-20.m3u8
│   └── ListenBrainz-Weekly-....m3u8
│       （Navidrome 会自动导入为歌单）
└── NetEase/
    └── 歌单名/                     # 同步的网易云歌单
        ├── 歌手 - 歌名.mp3
        └── 歌单名.m3u8
```

## 状态页

打开 `http://你的IP:8678`，可以看到：

- 网易云 Cookie 是否有效
- 下次运行时间
- 各曲目状态统计（已下载 / 已存在 / 失败 / 死亡）
- 最近运行记录
- 失败/重试队列，可逐条点"重试"
- "立即运行每日任务"按钮（非计划时间手动触发）

## 运行与排错

```bash
# 临时立即跑一次（不走调度器）
docker compose exec navidrome-sync python -m app.main --run-now

# 看日志
docker compose logs -f navidrome-sync

# 重启
docker compose restart
```

常见问题：

- **日推/完整歌单拉不到**：Cookie 失效或缺少 `MUSIC_U`，重新粘贴整串 Cookie
- **某首歌一直失败**：多为 VIP 曲目且各平台均无免费音源，会在重试若干次后标记为 `dead`，可在状态页删除
- **欧美/日文歌匹配错**：调高 `download.title_threshold`（更严格）或调低（更宽松）
- **Navidrome 没扫到新文件**：确认 `Scanner.WatcherWait` 未被关闭（默认开启，新文件 5 秒内触发扫描）

## 法律与合规

本项目仅供个人学习与自建曲库使用。下载行为依赖于网易云及第三方平台的非公开接口，可能违反其服务条款；VIP 内容请通过正版渠道获取。使用者自行承担相关风险，作者不对任何滥用后果负责。请勿用于商业用途或公开分发下载内容。

## 致谢

- [musicdl](https://github.com/CharlesPikachu/musicdl) — 多平台音乐下载库
- [Navidrome](https://github.com/navidrome/navidrome) — 开源音乐服务器
- [ListenBrainz](https://listenbrainz.org) / [Last.fm](https://www.last.fm) — 推荐数据来源
- [NCM-Downloader](https://github.com/xxynet/NCM-Downloader) — weapi 与下载思路参考