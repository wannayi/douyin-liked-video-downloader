"""领域模型。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class VideoItem:
    """点赞列表中的一个视频。"""

    video_id: str
    url: str
    description: str = ""
    author: str = ""


@dataclass(frozen=True)
class DownloadResult:
    """一次下载结果。"""

    path: str
    skipped_existing: bool = False


@dataclass(frozen=True)
class VideoResultDetail:
    """单个视频在本次运行中的结果明细。"""

    video_id: str
    title: str = ""
    author: str = ""
    path: str = ""
    error: str = ""


@dataclass(frozen=True)
class RunSummary:
    """一次任务的摘要。"""

    discovered: int
    skipped: int
    downloaded: int
    failed: int
    downloaded_items: tuple[VideoResultDetail, ...] = ()
    skipped_items: tuple[VideoResultDetail, ...] = ()
    failed_items: tuple[VideoResultDetail, ...] = ()
