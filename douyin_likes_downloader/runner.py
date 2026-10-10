"""一次任务执行流程。"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

from .browser import DouyinSession
from .config import AppConfig
from .downloader import DownloadError, VideoDownloader
from .models import RunSummary, VideoResultDetail
from .state import load_state, save_state


def run_once(config: AppConfig, logger: logging.Logger | None = None) -> RunSummary:
    logger = logger or logging.getLogger(__name__)
    config.ensure_directories()
    state = load_state(config.state_path)
    state.last_run_at = datetime.now(timezone.utc).isoformat()
    save_state(config.state_path, state)

    downloaded = 0
    skipped = 0
    failed = 0
    downloaded_items: list[VideoResultDetail] = []
    skipped_items: list[VideoResultDetail] = []
    failed_items: list[VideoResultDetail] = []
    downloader = VideoDownloader(config, logger)

    with DouyinSession(config, logger) as browser:
        items = browser.collect_liked_videos()
        for index, item in enumerate(items, start=1):
            if state.is_downloaded(item.video_id):
                skipped += 1
                record = state.downloaded.get(item.video_id)
                skipped_items.append(
                    VideoResultDetail(
                        video_id=item.video_id,
                        title=item.description,
                        author=item.author,
                        path=record.path if record else "",
                    )
                )
                logger.info("[%d/%d] 已下载，跳过：%s", index, len(items), item.video_id)
                continue

            logger.info("[%d/%d] 处理视频 %s：%s", index, len(items), item.video_id, item.description)
            sources = browser.find_media_sources(item)
            if not sources:
                failed += 1
                failed_items.append(
                    VideoResultDetail(
                        video_id=item.video_id,
                        title=item.description,
                        author=item.author,
                        error="未找到可下载的媒体地址",
                    )
                )
                logger.error("视频 %s 未找到可下载的媒体地址", item.video_id)
                continue

            result = None
            selected_source = None
            last_error = None
            # 失败或时长不符时尝试下一个高优先级候选，最多避免重复请求太多地址。
            for source_index, source in enumerate(sources[:6], start=1):
                expected_duration = source.expected_duration_seconds
                if (
                    source.source_kind == "player"
                    and expected_duration is not None
                    and expected_duration < config.minimum_video_duration_seconds
                ):
                    # 播放器自身可能只拿到短预览片段，不把它当成可信的原视频时长。
                    expected_duration = None
                try:
                    result = downloader.download(
                        item,
                        source.url,
                        content_type=source.content_type,
                        expected_duration_seconds=expected_duration,
                        referer=item.url,
                        user_agent=browser.user_agent,
                        cookie_header=browser.cookie_header(),
                    )
                    selected_source = source
                    break
                except DownloadError as exc:
                    last_error = exc
                    logger.warning(
                        "视频 %s 候选媒体 %d/%d 不可用：%s",
                        item.video_id,
                        source_index,
                        min(len(sources), 6),
                        exc,
                    )

            if result is None or selected_source is None:
                failed += 1
                failed_items.append(
                    VideoResultDetail(
                        video_id=item.video_id,
                        title=item.description,
                        author=item.author,
                        error=str(last_error or "所有媒体候选均下载失败"),
                    )
                )
                logger.error("视频 %s 的媒体候选均下载失败：%s", item.video_id, last_error)
                continue
            state.mark_downloaded(
                item.video_id,
                Path(result.path),
                item.description,
                (
                    selected_source.expected_duration_seconds
                    if selected_source.source_kind != "player"
                    or selected_source.expected_duration_seconds is None
                    or selected_source.expected_duration_seconds
                    >= config.minimum_video_duration_seconds
                    else None
                ),
            )
            save_state(config.state_path, state)
            if result.skipped_existing:
                skipped += 1
                skipped_items.append(
                    VideoResultDetail(
                        video_id=item.video_id,
                        title=item.description,
                        author=item.author,
                        path=result.path,
                    )
                )
                logger.info("文件已存在，登记状态：%s", result.path)
            else:
                downloaded += 1
                downloaded_items.append(
                    VideoResultDetail(
                        video_id=item.video_id,
                        title=item.description,
                        author=item.author,
                        path=result.path,
                    )
                )
                logger.info("下载完成：%s", result.path)

    # 只有本次发现的所有项目都成功处理，才把首次全量扫描标记为完成。
    if failed == 0:
        state.initialized = True
        state.last_success_at = datetime.now(timezone.utc).isoformat()
        save_state(config.state_path, state)
    else:
        logger.warning("本次有 %d 个视频失败，首次全量状态不会提前完成；下次运行会重试。", failed)

    return RunSummary(
        discovered=len(items),
        skipped=skipped,
        downloaded=downloaded,
        failed=failed,
        downloaded_items=tuple(downloaded_items),
        skipped_items=tuple(skipped_items),
        failed_items=tuple(failed_items),
    )
