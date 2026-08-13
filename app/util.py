"""通用工具：文件名清洗、文本归一化、限速器、日志。"""

import logging
import re
import sys
import time
import unicodedata

try:
    from opencc import OpenCC
    _t2s = OpenCC("t2s")
except Exception:
    _t2s = None

ILLEGAL_CHARS = r'[\\/*?:"<>|]'
_logger_initialized = False


def setup_logging(log_file=None):
    global _logger_initialized
    if _logger_initialized:
        return
    handlers = [logging.StreamHandler(sys.stdout)]
    if log_file:
        handlers.append(logging.FileHandler(log_file, encoding="utf-8"))
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=handlers,
    )
    _logger_initialized = True


def safe_name(name: str, maxlen: int = 120) -> str:
    """清洗文件系统非法字符。"""
    name = re.sub(ILLEGAL_CHARS, " ", str(name)).strip()
    name = re.sub(r"\s+", " ", name)
    return name[:maxlen].strip() or "unknown"


# 归一化时需要剥离的噪音：括号备注、feat、版本后缀等
_NOISE_PATTERNS = [
    r"[\(\（\[【].*?[\)\）\]】]",           # 各种括号及内容
    r"(?i)\bfeat\.?\b.*$", r"(?i)\bft\.?\b.*$",
    r"(?i)\bwith\b.*$",
    r"(?i)-\s*(live|remix|remaster(ed)?|acoustic|version|single|edit|deluxe).*$",
    r"(?i)\s-\s.*(版|ver\.?).*$",           # 中文"xxx版"后缀
]


def normalize(text: str) -> str:
    """归一化歌曲/歌手名用于匹配与去重（含繁简转换）。"""
    if not text:
        return ""
    text = unicodedata.normalize("NFKC", str(text))
    if _t2s is not None:
        try:
            text = _t2s.convert(text)
        except Exception:
            pass
    text = text.lower()
    for pat in _NOISE_PATTERNS:
        text = re.sub(pat, " ", text)
    text = re.sub(r"[^\w\s一-鿿぀-ヿ가-힯]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def track_key(artists, title: str) -> str:
    """去重主键：归一化的 首艺术家::标题。"""
    if isinstance(artists, str):
        artists = [artists]
    first = normalize(artists[0]) if artists else ""
    return f"{first}::{normalize(title)}"


class RateLimiter:
    """简单的调用间隔限制器。"""

    def __init__(self, interval: float):
        self.interval = interval
        self._last = 0.0

    def wait(self):
        delta = time.monotonic() - self._last
        if delta < self.interval:
            time.sleep(self.interval - delta)
        self._last = time.monotonic()
