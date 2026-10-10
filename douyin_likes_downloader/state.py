"""下载状态的原子读写。"""

from __future__ import annotations

import json
import math
import os
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .media import is_valid_video_file


STATE_VERSION = 2


@dataclass
class DownloadRecord:
    video_id: str
    path: str
    title: str = ""
    downloaded_at: str = ""
    expected_duration_seconds: float | None = None
    alternate_paths: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        result = {
            "video_id": self.video_id,
            "path": self.path,
            "title": self.title,
            "downloaded_at": self.downloaded_at,
        }
        if self.expected_duration_seconds is not None:
            result["expected_duration_seconds"] = self.expected_duration_seconds
        if self.alternate_paths:
            result["alternate_paths"] = self.alternate_paths
        return result


@dataclass
class DownloadState:
    initialized: bool = False
    downloaded: dict[str, DownloadRecord] = field(default_factory=dict)
    last_run_at: str | None = None
    last_success_at: str | None = None

    def is_downloaded(
        self, video_id: str, *, minimum_duration_seconds: float | None = None
    ) -> bool:
        record = self.downloaded.get(video_id)
        if record is None:
            return False
        paths = [record.path, *record.alternate_paths]
        if minimum_duration_seconds is None:
            return any(Path(path).is_file() for path in paths)
        return is_valid_video_file(
            Path(record.path),
            minimum_seconds=minimum_duration_seconds,
            expected_seconds=record.expected_duration_seconds,
        )

    def mark_downloaded(
        self,
        video_id: str,
        path: Path,
        title: str = "",
        expected_duration_seconds: float | None = None,
    ) -> None:
        self.downloaded[video_id] = DownloadRecord(
            video_id=video_id,
            path=str(path),
            title=title,
            downloaded_at=datetime.now(timezone.utc).isoformat(),
            expected_duration_seconds=expected_duration_seconds,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": STATE_VERSION,
            "initialized": self.initialized,
            "downloaded": {
                video_id: record.to_dict() for video_id, record in self.downloaded.items()
            },
            "last_run_at": self.last_run_at,
            "last_success_at": self.last_success_at,
        }


def _record_from_dict(video_id: str, raw: Any) -> DownloadRecord | None:
    if not isinstance(raw, dict):
        return None
    path = raw.get("path")
    if not isinstance(path, str) or not path:
        return None
    raw_expected_duration = raw.get("expected_duration_seconds")
    expected_duration = (
        float(raw_expected_duration)
        if isinstance(raw_expected_duration, (int, float))
        and not isinstance(raw_expected_duration, bool)
        and math.isfinite(raw_expected_duration)
        else None
    )
    raw_alternate_paths = raw.get("alternate_paths", [])
    alternate_paths = (
        [value for value in raw_alternate_paths if isinstance(value, str) and value]
        if isinstance(raw_alternate_paths, list)
        else []
    )
    return DownloadRecord(
        video_id=str(raw.get("video_id") or video_id),
        path=path,
        title=str(raw.get("title") or ""),
        downloaded_at=str(raw.get("downloaded_at") or ""),
        expected_duration_seconds=expected_duration,
        alternate_paths=alternate_paths,
    )


def load_state(path: Path) -> DownloadState:
    if not path.exists():
        return DownloadState()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        # 状态损坏时不删除原文件，下一次保存会覆盖为新状态；下载目录仍会
        # 通过文件名去重，避免已经成功的文件被重复下载。
        return DownloadState()
    if not isinstance(raw, dict):
        return DownloadState()

    records: dict[str, DownloadRecord] = {}
    raw_downloaded = raw.get("downloaded", {})
    if isinstance(raw_downloaded, dict):
        for video_id, record in raw_downloaded.items():
            parsed = _record_from_dict(str(video_id), record)
            if parsed:
                records[str(video_id)] = parsed

    return DownloadState(
        initialized=bool(raw.get("initialized", False)),
        downloaded=records,
        last_run_at=raw.get("last_run_at") if isinstance(raw.get("last_run_at"), str) else None,
        last_success_at=(
            raw.get("last_success_at")
            if isinstance(raw.get("last_success_at"), str)
            else None
        ),
    )


def save_state(path: Path, state: DownloadState) -> None:
    """同目录临时文件 + os.replace，防止任务中断留下半个 JSON。"""

    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f"{path.stem}_", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(state.to_dict(), handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    finally:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass
