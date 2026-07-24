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
    dl_quality: str
    dl_interval: float
    dl_sources_timeout: int
    title_threshold: int
    max_duration_diff: int
    cron: str
    run_on_startup: bool
    web_host: str
    web_port: int
    _path: Path = field(default_factory=Path)
    _raw: dict = field(default_factory=dict)

    def save(self):
        """将当前配置写回 YAML 文件。"""
        raw = self._raw.copy()
        raw["music_dir"] = str(self.music_dir)
        raw["data_dir"] = str(self.data_dir)
        raw["ncm_api_url"] = self.ncm_api_url
        raw["navidrome"] = {"url": self.navidrome.url, "username": self.navidrome.username, "password": self.navidrome.password}
        raw["sources"] = {}
        for name, sc in self.sources.items():
            d = {"enabled": sc.enabled}
            d.update(sc.extra)
            raw["sources"][name] = d
        raw["discover_daily_limit"] = self.discover_daily_limit
        raw["download"]["sources"] = self.dl_sources
        raw["download"]["interval_seconds"] = self.dl_interval
        raw["download"]["title_threshold"] = self.title_threshold
        raw["download"]["max_duration_diff"] = self.max_duration_diff
        raw["schedule"] = raw.get("schedule", {})
        raw["schedule"]["cron"] = self.cron
        raw["schedule"]["run_on_startup"] = self.run_on_startup
        raw["web"]["host"] = self.web_host
        raw["web"]["port"] = self.web_port
        with open(self._path, "w", encoding="utf-8") as f:
            yaml.dump(raw, f, default_flow_style=False, allow_unicode=True, sort_keys=False)


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
        dl_sources=list(dl.get("sources", ["netease", "kuwo", "migu", "bodian", "qq"])),
        dl_quality=str(dl.get("quality", "lossless")),
        dl_interval=float(dl.get("interval_seconds", 2.0)),
        dl_sources_timeout=int(dl.get("timeout", 120)),
        title_threshold=int(dl.get("title_threshold", 85)),
        max_duration_diff=int(dl.get("max_duration_diff", 12)),
        cron=str(sch.get("cron", "30 4 * * *")),
        run_on_startup=bool(sch.get("run_on_startup", False)),
        web_host=str(web.get("host", "0.0.0.0")),
        web_port=int(web.get("port", 8678)),
    )
