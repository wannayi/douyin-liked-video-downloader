"""命令行界面。"""

from __future__ import annotations

import argparse
import logging
import sys

from .browser import BrowserError, DouyinSession
from .config import ConfigError, load_config
from .notifier import send_failure_report, send_run_report
from .runner import run_once
from .scheduler import SchedulerError, install_task, uninstall_task


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="每天下载抖音账号新增点赞视频")
    subparsers = parser.add_subparsers(dest="command", required=True)
    for name, help_text in (
        ("login", "打开浏览器手动登录并保存登录态"),
        ("run", "立即执行一次扫描与下载"),
        ("install-task", "安装每天指定时间运行的 Windows 任务"),
        ("uninstall-task", "删除已安装的 Windows 任务"),
    ):
        subparser = subparsers.add_parser(name, help=help_text)
        subparser.add_argument("--config", default="config.json", help="配置文件路径")
    return parser


def _setup_logging(config) -> logging.Logger:
    config.ensure_directories()
    logger = logging.getLogger("douyin_likes_downloader")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(formatter)
    logger.addHandler(console)
    file_handler = logging.FileHandler(config.log_path, encoding="utf-8")
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    return logger


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    config = None
    logger = None
    try:
        config = load_config(args.config)
        if args.command == "install-task":
            install_task(config)
            print(f"已安装任务：{config.task_name}，每天 {config.schedule_time} 执行。")
            return 0
        if args.command == "uninstall-task":
            uninstall_task(config)
            print(f"已删除任务：{config.task_name}")
            return 0

        logger = _setup_logging(config)
        if args.command == "login":
            # login 必须可见，不能沿用 headless 配置。
            with DouyinSession(config, logger, headless=False) as browser:
                browser.login()
            print("登录态保存完成。现在可以运行 python app.py run。")
            return 0

        summary = run_once(config, logger)
        send_run_report(config, summary, logger)
        print(
            "本次完成：发现 {0}，新下载 {1}，跳过 {2}，失败 {3}。".format(
                summary.discovered, summary.downloaded, summary.skipped, summary.failed
            )
        )
        return 1 if summary.failed else 0
    except (ConfigError, BrowserError, SchedulerError) as exc:
        if args.command == "run" and config is not None:
            send_failure_report(config, exc, logger)
        print(f"错误：{exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        if args.command == "run" and config is not None:
            if logger is not None:
                logger.exception("运行过程中发生未处理异常")
            send_failure_report(config, exc, logger)
        print(f"运行失败：{exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("已取消。", file=sys.stderr)
        return 130
