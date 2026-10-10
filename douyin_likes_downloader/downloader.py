"""媒体文件下载。"""

from __future__ import annotations

import logging
import shutil
import subprocess
import urllib.request
from pathlib import Path

from .config import AppConfig
from .media import is_video_duration_valid, mp4_duration_seconds
from .models import DownloadResult, VideoItem
from .utils import choose_extension, existing_video_path, output_filename


class DownloadError(RuntimeError):
    """媒体下载失败。"""


class VideoDownloader:
    def __init__(self, config: AppConfig, logger: logging.Logger | None = None):
        self.config = config
        self.logger = logger or logging.getLogger(__name__)

    def download(
        self,
        item: VideoItem,
        source_url: str,
        *,
        content_type: str = "",
        expected_duration_seconds: float | None = None,
        referer: str | None = None,
        user_agent: str = "Mozilla/5.0",
        cookie_header: str = "",
    ) -> DownloadResult:
        self.config.output_dir.mkdir(parents=True, exist_ok=True)
        existing = existing_video_path(
            self.config.output_dir,
            item.video_id,
            minimum_duration_seconds=self.config.minimum_video_duration_seconds,
            expected_duration_seconds=expected_duration_seconds,
        )
        if existing is not None:
            return DownloadResult(path=str(existing), skipped_existing=True)
        if source_url.startswith("blob:"):
            raise DownloadError("浏览器返回了 blob 地址，无法直接下载")
        if not source_url.startswith(("http://", "https://")):
            raise DownloadError(f"不支持的媒体地址：{source_url[:120]}")

        extension = choose_extension(source_url, content_type)
        destination = self.config.output_dir / output_filename(
            item.video_id, item.description, extension
        )
        # 保留旧的短片/损坏文件，完整文件使用另一个名字，不覆盖用户已有内容。
        if destination.exists():
            base = destination.with_name(f"{destination.stem}_完整{destination.suffix}")
            destination = base
            suffix = 2
            while destination.exists():
                destination = base.with_name(
                    f"{base.stem}_{suffix}{base.suffix}"
                )
                suffix += 1
        temporary = destination.with_name(destination.name + ".part")
        if temporary.exists():
            temporary.unlink()

        headers = {
            "User-Agent": user_agent,
            "Referer": referer or item.url,
        }
        if cookie_header:
            headers["Cookie"] = cookie_header

        try:
            if ".m3u8" in source_url.lower() or "mpegurl" in content_type.lower():
                self._download_hls(source_url, temporary, headers)
            else:
                self._download_http(source_url, temporary, headers)
            if not temporary.exists() or temporary.stat().st_size < 1024:
                raise DownloadError("下载结果为空或文件过小")
            self._validate_download(
                temporary,
                expected_duration_seconds,
                media_extension=extension,
            )
            temporary.replace(destination)
        except Exception:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass
            raise
        return DownloadResult(path=str(destination), skipped_existing=False)

    def _validate_download(
        self,
        path: Path,
        expected_duration_seconds: float | None,
        *,
        media_extension: str,
    ) -> None:
        # 下载临时文件以 .part 结尾，不能用临时路径的 suffix 判断媒体类型。
        if media_extension.lower() not in {".mp4", ".mov"}:
            return
        duration = mp4_duration_seconds(path)
        if duration is None:
            raise DownloadError("下载结果不是有效的 MP4/MOV 容器，可能拿到了页面或媒体片段")
        if not is_video_duration_valid(
            duration,
            minimum_seconds=self.config.minimum_video_duration_seconds,
            expected_seconds=expected_duration_seconds,
        ):
            if expected_duration_seconds is not None:
                raise DownloadError(
                    f"媒体时长不完整：下载到 {duration:.2f} 秒，"
                    f"页面标记约 {expected_duration_seconds:.2f} 秒"
                )
            raise DownloadError(
                f"媒体只有 {duration:.2f} 秒，低于最短有效时长 "
                f"{self.config.minimum_video_duration_seconds:.2f} 秒"
            )

    def _download_http(self, source_url: str, temporary: Path, headers: dict[str, str]) -> None:
        request = urllib.request.Request(source_url, headers=headers, method="GET")
        try:
            with urllib.request.urlopen(request, timeout=self.config.download_timeout_seconds) as response:
                status = getattr(response, "status", 200)
                if status >= 400:
                    raise DownloadError(f"媒体服务器返回 HTTP {status}")
                if status == 206 or response.headers.get("Content-Range"):
                    raise DownloadError("媒体服务器只返回了部分视频内容，拒绝保存为完整视频")
                with temporary.open("wb") as handle:
                    while True:
                        chunk = response.read(1024 * 1024)
                        if not chunk:
                            break
                        handle.write(chunk)
        except DownloadError:
            raise
        except Exception as exc:
            raise DownloadError(f"下载媒体失败：{exc}") from exc

    def _download_hls(self, source_url: str, temporary: Path, headers: dict[str, str]) -> None:
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            raise DownloadError(
                "检测到 HLS (.m3u8) 播放地址，但系统未找到 ffmpeg。"
                "请安装 ffmpeg 并加入 PATH 后重试。"
            )
        header_text = "\r\n".join(f"{key}: {value}" for key, value in headers.items()) + "\r\n"
        command = [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-headers",
            header_text,
            "-i",
            source_url,
            "-c",
            "copy",
            "-movflags",
            "+faststart",
            "-f",
            "mp4",
            str(temporary),
        ]
        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=self.config.download_timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise DownloadError("ffmpeg 下载 HLS 超时") from exc
        if completed.returncode != 0:
            detail = (completed.stderr or "").strip()[-800:]
            raise DownloadError(f"ffmpeg 下载 HLS 失败：{detail}")
