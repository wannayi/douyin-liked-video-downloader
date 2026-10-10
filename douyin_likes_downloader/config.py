"""配置加载与路径解析。"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class ConfigError(ValueError):
    """配置文件不合法。"""


@dataclass(frozen=True)
class AppConfig:
    """运行配置。

    相对路径都以配置文件所在目录为基准，这样从任务计划程序运行时不依赖
    当前工作目录。
    """

    config_path: Path
    likes_url: str
    output_dir: Path
    data_dir: Path
    headless: bool
    browser_channel: str | None
    max_scroll_rounds: int
    scroll_pause_seconds: float
    detail_wait_seconds: float
    page_timeout_seconds: int
    download_timeout_seconds: int
    minimum_video_duration_seconds: float
    max_items: int
    schedule_time: str
    task_name: str
    feishu_webhook_url: str
    feishu_webhook_secret: str

    @property
    def state_path(self) -> Path:
        return self.data_dir / "state.json"

    @property
    def browser_profile_dir(self) -> Path:
        return self.data_dir / "browser-profile"

    @property
    def storage_state_path(self) -> Path:
        """登录态快照路径。

        当前运行优先使用 persistent browser profile；这个快照用于备份和
        检查登录态，不包含账号密码。
        """

        return self.data_dir / "storage_state.json"

    @property
    def login_marker_path(self) -> Path:
        """只有交互登录验证通过后才会生成的标记文件。"""

        return self.data_dir / "login.success"

    @property
    def log_path(self) -> Path:
        return self.data_dir / "run.log"

    def ensure_directories(self) -> None:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.data_dir.mkdir(parents=True, exist_ok=True)


def _resolve_path(value: Any, base_dir: Path, field_name: str) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"配置项 {field_name!r} 必须是非空字符串")
    path = Path(value)
    return path if path.is_absolute() else (base_dir / path)


def _positive_int(value: Any, field_name: str, *, allow_zero: bool = False) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigError(f"配置项 {field_name!r} 必须是整数")
    minimum = 0 if allow_zero else 1
    if value < minimum:
        raise ConfigError(f"配置项 {field_name!r} 必须大于等于 {minimum}")
    return value


def _positive_float(value: Any, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigError(f"配置项 {field_name!r} 必须是数字")
    value = float(value)
    if not math.isfinite(value) or value <= 0:
        raise ConfigError(f"配置项 {field_name!r} 必须大于 0")
    return value


def _optional_string(value: Any, field_name: str) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ConfigError(f"配置项 {field_name!r} 必须是字符串")
    return value.strip()


def _validate_time(value: Any) -> str:
    if not isinstance(value, str):
        raise ConfigError("配置项 'schedule_time' 必须是 HH:MM 字符串")
    parts = value.split(":")
    if len(parts) != 2:
        raise ConfigError("配置项 'schedule_time' 必须是 HH:MM，例如 05:00")
    try:
        hour, minute = (int(part) for part in parts)
    except ValueError as exc:
        raise ConfigError("配置项 'schedule_time' 必须是 HH:MM，例如 05:00") from exc
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ConfigError("配置项 'schedule_time' 超出范围")
    return f"{hour:02d}:{minute:02d}"


def load_config(path: str | Path = "config.json") -> AppConfig:
    """读取并校验 JSON 配置。"""

    config_path = Path(path).expanduser().resolve()
    if not config_path.exists():
        raise ConfigError(
            f"找不到配置文件 {config_path}。请先复制 config.example.json 为 config.json。"
        )
    try:
        raw = json.loads(config_path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ConfigError(f"无法读取配置文件：{exc}") from exc
    except json.JSONDecodeError as exc:
        raise ConfigError(f"配置文件不是合法 JSON：{exc}") from exc
    if not isinstance(raw, dict):
        raise ConfigError("配置文件顶层必须是 JSON 对象")

    base_dir = config_path.parent
    likes_url = raw.get("likes_url", "https://www.douyin.com/user/self?showTab=like")
    if not isinstance(likes_url, str) or not likes_url.startswith(("http://", "https://")):
        raise ConfigError("配置项 'likes_url' 必须是 http(s) URL")

    output_dir = _resolve_path(
        raw.get("output_dir", r"H:\Movie\Douyin"), base_dir, "output_dir"
    )
    data_dir = _resolve_path(raw.get("data_dir", "data"), base_dir, "data_dir")

    headless = raw.get("headless", True)
    if not isinstance(headless, bool):
        raise ConfigError("配置项 'headless' 必须是布尔值")

    browser_channel = raw.get("browser_channel", "msedge")
    if browser_channel is not None and not isinstance(browser_channel, str):
        raise ConfigError("配置项 'browser_channel' 必须是字符串或 null")

    task_name = raw.get("task_name", "DouyinLikedVideosDownloader")
    if not isinstance(task_name, str) or not task_name.strip():
        raise ConfigError("配置项 'task_name' 必须是非空字符串")

    feishu_webhook_url = _optional_string(raw.get("feishu_webhook_url", ""), "feishu_webhook_url")
    if feishu_webhook_url and not feishu_webhook_url.startswith(("http://", "https://")):
        raise ConfigError("配置项 'feishu_webhook_url' 必须是 http(s) URL")
    feishu_webhook_secret = _optional_string(
        raw.get("feishu_webhook_secret", ""), "feishu_webhook_secret"
    )
    if feishu_webhook_secret and not feishu_webhook_url:
        raise ConfigError("配置了 'feishu_webhook_secret' 时必须同时配置 'feishu_webhook_url'")

    return AppConfig(
        config_path=config_path,
        likes_url=likes_url,
        output_dir=output_dir,
        data_dir=data_dir,
        headless=headless,
        browser_channel=browser_channel,
        max_scroll_rounds=_positive_int(raw.get("max_scroll_rounds", 300), "max_scroll_rounds"),
        scroll_pause_seconds=_positive_float(
            raw.get("scroll_pause_seconds", 1.5), "scroll_pause_seconds"
        ),
        detail_wait_seconds=_positive_float(
            raw.get("detail_wait_seconds", 4.0), "detail_wait_seconds"
        ),
        page_timeout_seconds=_positive_int(
            raw.get("page_timeout_seconds", 60), "page_timeout_seconds"
        ),
        download_timeout_seconds=_positive_int(
            raw.get("download_timeout_seconds", 180), "download_timeout_seconds"
        ),
        minimum_video_duration_seconds=_positive_float(
            raw.get("minimum_video_duration_seconds", 3.0),
            "minimum_video_duration_seconds",
        ),
        max_items=_positive_int(raw.get("max_items", 0), "max_items", allow_zero=True),
        schedule_time=_validate_time(raw.get("schedule_time", "05:00")),
        task_name=task_name.strip(),
        feishu_webhook_url=feishu_webhook_url,
        feishu_webhook_secret=feishu_webhook_secret,
    )
