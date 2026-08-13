"""配置加载：config.yaml + 环境变量覆盖。"""

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml

DEFAULT_CONFIG_PATHS = [
    Path("/app/config.yaml"),
    Path("./config.yaml"),
    Path(__file__).resolve().parent.parent / "config.yaml",
]


@dataclass
class NavidromeCfg:
    url: str = ""
    username: str = ""
    password: str = ""

    @property
    def enabled(self) -> bool:
        return bool(self.url and self.username and self.password)


@dataclass
class SourceCfg:
    enabled: bool = False
    extra: dict = field(default_factory=dict)


@dataclass
class Config:
    music_dir: Path
    data_dir: Path
    navidrome: NavidromeCfg
    ncm_api_url: str
    netease_cookie: str
    sources: dict  # name -> SourceCfg
    discover_daily_limit: int
    dl_sources: list
    dl_interval: float
    title_threshold: int
    max_duration_diff: int
    cron: str
    run_on_startup: bool
    web_host: str
    web_port: int
    web_auth_user: str
    web_auth_password: str
    _path: Path = field(default_factory=Path)
    _raw: dict = field(default_factory=dict)


def _find_config_file() -> Path:
    env = os.environ.get("SYNC_CONFIG")
    if env:
        return Path(env)
    for p in DEFAULT_CONFIG_PATHS:
        if p.exists():
            return p
    raise FileNotFoundError(
        f"未找到 config.yaml，搜索路径: {[str(p) for p in DEFAULT_CONFIG_PATHS]}"
    )


def load() -> Config:
    cfg_path = _find_config_file()
    with open(cfg_path, encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
        if not isinstance(raw, dict):
            raw = {}

    data_dir = Path(raw.get("data_dir", "/app/data"))
    music_dir = Path(raw.get("music_dir", "/music"))

    nav_raw = raw.get("navidrome") or {}
    navidrome = NavidromeCfg(
        url=os.environ.get("NAVIDROME_URL") or nav_raw.get("url", ""),
        username=os.environ.get("NAVIDROME_USERNAME") or nav_raw.get("username", ""),
        password=os.environ.get("NAVIDROME_PASSWORD") or nav_raw.get("password", ""),
    )

    nc = raw.get("netease") or {}
    cookie_file = Path(nc.get("cookie_file", data_dir / "cookie.txt"))
    cookie = ""
    if cookie_file.exists():
        cookie = cookie_file.read_text(encoding="utf-8").strip()

    sources = {}
    for name, sc in (raw.get("sources") or {}).items():
        sc = sc or {}
        extra = {k: v for k, v in sc.items() if k != "enabled"}
        sources[name] = SourceCfg(enabled=bool(sc.get("enabled", False)), extra=extra)

    dl = raw.get("download") or {}
    sch = raw.get("schedule") or {}
    web = raw.get("web") or {}

    return Config(
        _path=cfg_path,
        _raw=raw,
        music_dir=music_dir,
        data_dir=data_dir,
        navidrome=navidrome,
        ncm_api_url=str(raw.get("ncm_api_url", "http://ncm-api:3000")),
        netease_cookie=cookie,
        sources=sources,
        discover_daily_limit=int(raw.get("discover_daily_limit", 40)),
        dl_sources=list(dl.get("sources", ["ytdlp", "netease", "kuwo", "migu", "bodian", "qq"])),
        dl_interval=float(dl.get("interval_seconds", 2.0)),
        title_threshold=int(dl.get("title_threshold", 85)),
        max_duration_diff=int(dl.get("max_duration_diff", 12)),
        cron=str(sch.get("cron", "30 4 * * *")),
        run_on_startup=bool(sch.get("run_on_startup", False)),
        web_host=str(web.get("host", "0.0.0.0")),
        web_port=int(web.get("port", 8678)),
        web_auth_user=str(os.environ.get("SYNC_AUTH_USER") or web.get("auth_user", "")),
        web_auth_password=str(os.environ.get("SYNC_AUTH_PASSWORD") or web.get("auth_password", "")),
    )
