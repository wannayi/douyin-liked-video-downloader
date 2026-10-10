"""Windows 任务计划程序集成。"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from .config import AppConfig


class SchedulerError(RuntimeError):
    """任务计划程序操作失败。"""


def build_task_command(config: AppConfig, *, python_executable: str | None = None) -> list[str]:
    """构造 schtasks 命令，便于测试和实际执行。"""

    if os.name != "nt":
        raise SchedulerError("install-task 仅支持 Windows")
    python_executable = python_executable or sys.executable
    # 任务的配置可以放在其他目录，但入口脚本始终是本项目根目录的 app.py。
    script_path = Path(__file__).resolve().parents[1] / "app.py"
    task_run = subprocess.list2cmdline(
        [
            str(Path(python_executable).resolve()),
            str(script_path.resolve()),
            "run",
            "--config",
            str(config.config_path.resolve()),
        ]
    )
    return [
        "schtasks.exe",
        "/Create",
        "/SC",
        "DAILY",
        "/ST",
        config.schedule_time,
        "/TN",
        config.task_name,
        "/TR",
        task_run,
        "/RL",
        "LIMITED",
        "/F",
    ]


def install_task(config: AppConfig) -> None:
    command = build_task_command(config)
    _run_schtasks(command, action="创建")


def uninstall_task(config: AppConfig) -> None:
    if os.name != "nt":
        raise SchedulerError("uninstall-task 仅支持 Windows")
    _run_schtasks(
        ["schtasks.exe", "/Delete", "/TN", config.task_name, "/F"],
        action="删除",
    )


def _run_schtasks(command: list[str], *, action: str) -> None:
    try:
        completed = subprocess.run(command, capture_output=True, text=True, check=False)
    except OSError as exc:
        raise SchedulerError(f"无法调用 schtasks.exe：{exc}") from exc
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()
        raise SchedulerError(f"{action}任务计划失败：{detail}")
