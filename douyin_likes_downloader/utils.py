"""通用字符串、URL 和文件名处理。"""

from __future__ import annotations

import re
from html import unescape
from pathlib import Path
from urllib.parse import urljoin, urlparse

from .media import is_valid_video_file


VIDEO_ID_PATTERN = re.compile(r"/video/(\d+)(?:[/?#]|$)", re.IGNORECASE)
INVALID_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
RESERVED_WINDOWS_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


def normalize_url(url: str, base_url: str) -> str:
    """将页面中可能出现的相对链接转为绝对链接。"""

    return urljoin(base_url, unescape(url).replace("\\/", "/")).split("#", 1)[0]


def extract_video_id(url: str) -> str | None:
    match = VIDEO_ID_PATTERN.search(url)
    return match.group(1) if match else None


def sanitize_filename(value: str, *, max_length: int = 90) -> str:
    """生成 Windows 和 macOS 都可用的文件名片段。"""

    value = re.sub(r"\s+", " ", (value or "")).strip()
    value = INVALID_FILENAME_CHARS.sub("_", value)
    value = value.rstrip(" .")
    if not value:
        value = "video"
    if value.upper() in RESERVED_WINDOWS_NAMES:
        value = f"_{value}"
    return value[:max_length].rstrip(" .") or "video"


def choose_extension(url: str, content_type: str = "") -> str:
    """根据媒体 URL 或 Content-Type 选择扩展名。"""

    content_type = content_type.lower().split(";", 1)[0].strip()
    if "mpegurl" in content_type or "m3u8" in url.lower():
        return ".mp4"
    if content_type == "video/webm" or ".webm" in url.lower():
        return ".webm"
    if content_type == "video/quicktime" or ".mov" in url.lower():
        return ".mov"
    return ".mp4"


def existing_video_path(
    output_dir: Path,
    video_id: str,
    *,
    minimum_duration_seconds: float | None = None,
    expected_duration_seconds: float | None = None,
) -> Path | None:
    """查找同一视频 ID 的已有文件，避免标题变化导致重复下载。"""

    for path in output_dir.glob(f"{video_id}_*"):
        if path.suffix.lower() in {".mp4", ".webm", ".mov"} and is_valid_video_file(
            path,
            minimum_seconds=minimum_duration_seconds,
            expected_seconds=expected_duration_seconds,
        ):
            return path
    return None


def output_filename(video_id: str, description: str, extension: str) -> str:
    title = sanitize_filename(description)
    return f"{video_id}_{title}{extension}"


def is_media_url(url: str) -> bool:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        return False
    # 详情页本身也含有 /video/<数字>，不能把它误判成媒体文件。
    if re.search(r"/video/\d+/?$", parsed.path, re.IGNORECASE):
        return False
    lowered = url.lower()
    return any(marker in lowered for marker in (".mp4", ".m3u8", ".webm", ".mov", "video"))
