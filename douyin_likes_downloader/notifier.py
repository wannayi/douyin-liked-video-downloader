"""飞书机器人运行结果通知。"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import time
import urllib.request
from datetime import datetime

from .config import AppConfig
from .models import RunSummary, VideoResultDetail


MAX_REPORT_CHARS = 28000


def _sign(timestamp: int, secret: str) -> str:
    signing_text = f"{timestamp}\n{secret}".encode("utf-8")
    digest = hmac.new(signing_text, digestmod=hashlib.sha256).digest()
    return base64.b64encode(digest).decode("ascii")


def format_run_report(summary: RunSummary, *, finished_at: datetime | None = None) -> str:
    finished_at = finished_at or datetime.now().astimezone()
    if summary.failed:
        result = "部分失败"
    elif summary.discovered == 0:
        result = "完成，但未发现视频"
    else:
        result = "完成"

    lines = [
        "抖音点赞视频下载结果",
        f"运行完成：{finished_at.astimezone().strftime('%Y-%m-%d %H:%M:%S %z')}",
        f"结果：{result}",
        f"发现视频：{summary.discovered} 个",
        f"新下载：{summary.downloaded} 个",
        f"已跳过：{summary.skipped} 个",
        f"失败：{summary.failed} 个",
    ]
    if summary.discovered == 0:
        lines.append("提示：未采集到视频链接，请检查登录态或点赞页结构。")
    return "\n".join(lines)


def format_failure_report(error: BaseException, *, finished_at: datetime | None = None) -> str:
    finished_at = finished_at or datetime.now().astimezone()
    return "\n".join(
        [
            "抖音点赞视频下载结果",
            f"运行完成：{finished_at.astimezone().strftime('%Y-%m-%d %H:%M:%S %z')}",
            "结果：运行异常",
            f"异常：{type(error).__name__}: {error}",
        ]
    )


def _text_line(text: str) -> list[dict[str, str]]:
    return [{"tag": "text", "text": text}]


def _clip(value: str, limit: int = 240) -> str:
    value = " ".join((value or "").split())
    return value if len(value) <= limit else value[: limit - 1] + "…"


def _detail_lines(detail: VideoResultDetail, *, failed: bool) -> list[list[dict[str, str]]]:
    title = _clip(detail.title or "未命名视频")
    lines = [
        _text_line(f"• {title}"),
        _text_line(f"  ID：{detail.video_id}"),
    ]
    if detail.author:
        lines.append(_text_line(f"  作者：{_clip(detail.author, 100)}"))
    if failed:
        lines.append(_text_line(f"  原因：{_clip(detail.error or '未知错误', 300)}"))
    elif detail.path:
        lines.append(_text_line(f"  保存：{_clip(detail.path, 360)}"))
    return lines


def _add_detail_section(
    content: list[list[dict[str, str]]],
    heading: str,
    items: tuple[VideoResultDetail, ...],
    count: int,
    *,
    failed: bool = False,
) -> None:
    content.append(_text_line(f"{heading}（{count}）"))
    if not items:
        content.append(_text_line("  无"))
        return

    current_chars = sum(len(part.get("text", "")) for row in content for part in row)
    omitted = 0
    for index, item in enumerate(items):
        item_lines = _detail_lines(item, failed=failed)
        item_chars = sum(len(part.get("text", "")) for row in item_lines for part in row)
        if current_chars + item_chars > MAX_REPORT_CHARS:
            omitted = len(items) - index
            break
        content.extend(item_lines)
        current_chars += item_chars
    if omitted:
        content.append(_text_line(f"  …报告过长，已省略其余 {omitted} 个视频"))


def build_run_report_payload(
    summary: RunSummary,
    *,
    finished_at: datetime | None = None,
) -> dict[str, object]:
    finished_at = finished_at or datetime.now().astimezone()
    if summary.failed:
        result = "部分失败"
    elif summary.discovered == 0:
        result = "完成，但未发现视频"
    else:
        result = "完成"

    content: list[list[dict[str, str]]] = [
        _text_line("📊 运行概览"),
        _text_line(f"完成时间：{finished_at.astimezone().strftime('%Y-%m-%d %H:%M:%S %z')}"),
        _text_line(f"结果：{result}"),
        _text_line(f"发现视频：{summary.discovered} 个"),
        _text_line(f"新下载：{summary.downloaded} 个"),
        _text_line(f"已跳过：{summary.skipped} 个"),
        _text_line(f"失败：{summary.failed} 个"),
    ]
    if summary.discovered == 0:
        content.append(_text_line("⚠️ 未采集到视频链接，请检查登录态或点赞页结构。"))
    content.append(_text_line(""))
    _add_detail_section(content, "📥 新下载", summary.downloaded_items, summary.downloaded)
    content.append(_text_line(""))
    _add_detail_section(content, "⏭️ 已跳过", summary.skipped_items, summary.skipped)
    content.append(_text_line(""))
    _add_detail_section(
        content,
        "❌ 失败",
        summary.failed_items,
        summary.failed,
        failed=True,
    )
    return {
        "msg_type": "post",
        "content": {
            "post": {
                "zh_cn": {
                    "title": "抖音点赞视频下载结果",
                    "content": content,
                }
            }
        },
    }


def build_failure_report_payload(
    error: BaseException,
    *,
    finished_at: datetime | None = None,
) -> dict[str, object]:
    finished_at = finished_at or datetime.now().astimezone()
    content = [
        _text_line("📊 运行概览"),
        _text_line(f"完成时间：{finished_at.astimezone().strftime('%Y-%m-%d %H:%M:%S %z')}"),
        _text_line("结果：运行异常"),
        _text_line(f"异常：{type(error).__name__}: {_clip(str(error), 500)}"),
    ]
    return {
        "msg_type": "post",
        "content": {
            "post": {
                "zh_cn": {
                    "title": "抖音点赞视频下载结果",
                    "content": content,
                }
            }
        },
    }


def send_feishu_message(
    config: AppConfig,
    message: str | dict[str, object],
    logger: logging.Logger | None = None,
) -> bool:
    """发送通知；未配置或发送失败时返回 False，不向下载流程抛异常。"""

    logger = logger or logging.getLogger(__name__)
    if not config.feishu_webhook_url:
        logger.info("未配置飞书 Webhook，跳过运行结果通知")
        return False

    timestamp = int(time.time())
    payload: dict[str, object] = (
        message
        if isinstance(message, dict)
        else {"msg_type": "text", "content": {"text": message}}
    )
    if config.feishu_webhook_secret:
        payload["timestamp"] = str(timestamp)
        payload["sign"] = _sign(timestamp, config.feishu_webhook_secret)

    request = urllib.request.Request(
        config.feishu_webhook_url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            raw_body = response.read().decode("utf-8", errors="replace")
        result = json.loads(raw_body) if raw_body else {}
        if isinstance(result, dict) and result.get("code", 0) not in (0, None):
            raise RuntimeError(f"飞书返回错误 {result.get('code')}: {result.get('msg', '')}")
    except (OSError, ValueError, RuntimeError) as exc:
        logger.warning("飞书运行结果通知发送失败：%s", exc)
        return False

    logger.info("飞书运行结果通知已发送")
    return True


def send_run_report(
    config: AppConfig,
    summary: RunSummary,
    logger: logging.Logger | None = None,
) -> bool:
    return send_feishu_message(config, build_run_report_payload(summary), logger)


def send_failure_report(
    config: AppConfig,
    error: BaseException,
    logger: logging.Logger | None = None,
) -> bool:
    return send_feishu_message(config, build_failure_report_payload(error), logger)
