import unittest
from datetime import datetime, timezone
from pathlib import Path

from douyin_likes_downloader.config import load_config
from douyin_likes_downloader.models import RunSummary, VideoResultDetail
from douyin_likes_downloader.notifier import build_run_report_payload, format_run_report


class NotifierTests(unittest.TestCase):
    def test_format_run_report_contains_download_counts(self):
        report = format_run_report(
            RunSummary(discovered=7, skipped=2, downloaded=4, failed=1),
            finished_at=datetime(2026, 10, 10, 5, 0, tzinfo=timezone.utc),
        )
        self.assertIn("发现视频：7 个", report)
        self.assertIn("新下载：4 个", report)
        self.assertIn("已跳过：2 个", report)
        self.assertIn("失败：1 个", report)
        self.assertIn("部分失败", report)

    def test_config_accepts_optional_feishu_settings(self):
        config = load_config(Path("config.example.json"))
        self.assertEqual(config.feishu_webhook_url, "")
        self.assertEqual(config.feishu_webhook_secret, "")

    def test_rich_payload_contains_result_sections_and_details(self):
        summary = RunSummary(
            discovered=3,
            skipped=1,
            downloaded=1,
            failed=1,
            downloaded_items=(
                VideoResultDetail("100", "新下载视频", path="H:\\Movie\\100_视频.mp4"),
            ),
            skipped_items=(VideoResultDetail("200", "已存在视频", path="H:\\Movie\\200_视频.mp4"),),
            failed_items=(VideoResultDetail("300", "失败视频", error="HTTP 404"),),
        )
        payload = build_run_report_payload(summary)
        content = payload["content"]["post"]["zh_cn"]["content"]
        text = "\n".join(part["text"] for row in content for part in row)
        self.assertEqual(payload["msg_type"], "post")
        self.assertIn("📥 新下载（1）", text)
        self.assertIn("⏭️ 已跳过（1）", text)
        self.assertIn("❌ 失败（1）", text)
        self.assertIn("新下载视频", text)
        self.assertIn("HTTP 404", text)
