"""曲目匹配与校验：搜索结果 -> 目标曲目的置信度判断。"""

import logging

from rapidfuzz import fuzz

from .util import normalize

log = logging.getLogger(__name__)


def title_score(a: str, b: str) -> float:
    return fuzz.token_sort_ratio(normalize(a), normalize(b))


def artist_match(wanted: list, offered: list) -> bool:
    """任一歌手（归一化后）出现在候选歌手列表中即视为匹配。"""
    wanted_n = {normalize(a) for a in wanted if normalize(a)}
    offered_n = {normalize(a) for a in offered if normalize(a)}
    if not wanted_n or not offered_n:
        return False
    if wanted_n & offered_n:
        return True
    # 处理 "A/B" 或 "A, B" 这类合并写法
    for w in wanted_n:
        for o in offered_n:
            if w in o or o in w:
                return True
    return False


def duration_ok(wanted_ms, offered, tolerance_s: int) -> bool:
    """时长校验；任一缺失则放行。"""
    if not wanted_ms or not offered:
        return True
    offered_ms = offered * 1000 if offered < 10000 else offered  # 兼容秒/毫秒
    return abs(wanted_ms - offered_ms) <= tolerance_s * 1000


def is_match(track, candidate: dict, title_threshold: int = 85, max_duration_diff: int = 12) -> bool:
    """candidate 需含 name/artists，可选 duration(秒或毫秒)。"""
    score = title_score(track.title, candidate.get("name", ""))
    if score < title_threshold:
        return False
    if not artist_match(track.artists, candidate.get("artists", [])):
        return False
    if not duration_ok(track.duration_ms, candidate.get("duration"), max_duration_diff):
        return False
    return True


def best_match(track, candidates: list, title_threshold: int = 85, max_duration_diff: int = 12):
    """从候选列表中挑出最佳匹配，无匹配返回 None。

    排序优先级：归一化后完全一致 > 模糊分高 > 标题更短（更可能是原版而非 Cover/Live）。
    """
    matched = []
    for c in candidates:
        if is_match(track, c, title_threshold, max_duration_diff):
            exact = 1 if normalize(track.title) == normalize(c.get("name", "")) else 0
            score = title_score(track.title, c.get("name", ""))
            matched.append(((exact, score, -len(c.get("name", "").strip())), c))
    if not matched:
        return None
    matched.sort(key=lambda x: x[0], reverse=True)
    return matched[0][1]
