"""媒体容器完整性检查。"""

from __future__ import annotations

import math
from pathlib import Path


def _read_box_header(handle, offset: int, parent_end: int) -> tuple[bytes, int, int] | None:
    if offset < 0 or offset + 8 > parent_end:
        return None
    handle.seek(offset)
    header = handle.read(8)
    if len(header) != 8:
        return None

    size = int.from_bytes(header[:4], "big")
    header_size = 8
    if size == 1:
        extended_size = handle.read(8)
        if len(extended_size) != 8:
            return None
        size = int.from_bytes(extended_size, "big")
        header_size = 16
    elif size == 0:
        size = parent_end - offset

    end = offset + size
    if size < header_size or end > parent_end:
        return None
    return header[4:8], offset + header_size, end


def mp4_duration_seconds(path: Path) -> float | None:
    """读取 MP4/MOV 的 movie header 时长；不会把整个视频载入内存。"""

    try:
        file_size = path.stat().st_size
        with path.open("rb") as handle:
            offset = 0
            while offset + 8 <= file_size:
                box = _read_box_header(handle, offset, file_size)
                if box is None:
                    return None
                kind, payload_start, box_end = box
                if kind == b"moov":
                    child_offset = payload_start
                    while child_offset + 8 <= box_end:
                        child = _read_box_header(handle, child_offset, box_end)
                        if child is None:
                            return None
                        child_kind, payload_start, _ = child
                        if child_kind == b"mvhd":
                            handle.seek(payload_start)
                            full_box = handle.read(4)
                            if len(full_box) != 4:
                                return None
                            version = full_box[0]
                            if version == 0:
                                handle.seek(payload_start + 12)
                                values = handle.read(8)
                                if len(values) != 8:
                                    return None
                                timescale = int.from_bytes(values[:4], "big")
                                duration = int.from_bytes(values[4:], "big")
                            elif version == 1:
                                handle.seek(payload_start + 20)
                                values = handle.read(12)
                                if len(values) != 12:
                                    return None
                                timescale = int.from_bytes(values[:4], "big")
                                duration = int.from_bytes(values[4:], "big")
                            else:
                                return None
                            if timescale <= 0:
                                return None
                            seconds = duration / timescale
                            return seconds if math.isfinite(seconds) and seconds > 0 else None
                        child_offset = child[2]
                    return None
                offset = box_end
    except OSError:
        return None
    return None


def is_video_duration_valid(
    actual_seconds: float,
    *,
    minimum_seconds: float | None = None,
    expected_seconds: float | None = None,
) -> bool:
    if not math.isfinite(actual_seconds) or actual_seconds <= 0:
        return False
    if expected_seconds is not None and math.isfinite(expected_seconds) and expected_seconds > 0:
        allowed_shortfall = max(0.25, expected_seconds * 0.01)
        return actual_seconds + allowed_shortfall >= expected_seconds
    return minimum_seconds is None or actual_seconds >= minimum_seconds


def is_valid_video_file(
    path: Path,
    *,
    minimum_seconds: float | None = None,
    expected_seconds: float | None = None,
) -> bool:
    try:
        if not path.is_file() or path.stat().st_size < 1024:
            return False
    except OSError:
        return False

    if minimum_seconds is None and expected_seconds is None:
        return True

    if path.suffix.lower() in {".mp4", ".mov"}:
        duration = mp4_duration_seconds(path)
        return duration is not None and is_video_duration_valid(
            duration,
            minimum_seconds=minimum_seconds,
            expected_seconds=expected_seconds,
        )
    # WebM 的时长验证依赖外部探测器；保留文件大小校验，不误删已有媒体。
    return path.suffix.lower() == ".webm"
