"""推荐源抽象。"""

from dataclasses import dataclass, field


@dataclass
class Track:
    title: str
    artists: list
    album: str = ""
    duration_ms: int = 0
    ncm_id: int | None = None
    origin: str = ""            # 来源标记，如 netease_daily / listenbrainz / lastfm / playlist:xxx
    score: float = 1.0          # 推荐分数（聚合用）
    playlist: str = ""          # 目标歌单名（生成 m3u8 用），为空则进默认推荐歌单
    raw: dict = field(default_factory=dict)


class Source:
    """推荐源接口：每日产出一批 Track。"""

    name = "base"

    def fetch(self) -> list[Track]:
        raise NotImplementedError
