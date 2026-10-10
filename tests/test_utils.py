import unittest
from pathlib import Path
import tempfile

from douyin_likes_downloader.utils import (
    choose_extension,
    existing_video_path,
    extract_video_id,
    is_media_url,
    output_filename,
    sanitize_filename,
)


class UtilsTests(unittest.TestCase):
    def test_extract_video_id(self):
        self.assertEqual(extract_video_id("https://www.douyin.com/video/123456?modal_id=1"), "123456")
        self.assertIsNone(extract_video_id("https://www.douyin.com/user/abc"))

    def test_filename_is_safe(self):
        value = sanitize_filename('CON: 一个/视频?')
        self.assertNotIn(":", value)
        self.assertNotIn("/", value)
        self.assertFalse(value.endswith((".", " ")))
        self.assertEqual(output_filename("123", "测试", ".mp4"), "123_测试.mp4")

    def test_choose_extension(self):
        self.assertEqual(choose_extension("https://cdn.test/video.m3u8"), ".mp4")
        self.assertEqual(choose_extension("https://cdn.test/video.webm"), ".webm")

    def test_detail_page_is_not_media_url(self):
        self.assertFalse(is_media_url("https://www.douyin.com/video/123456?modal_id=123456"))

    def test_existing_video_path_uses_id_prefix(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            target = root / "123_old-title.mp4"
            target.write_bytes(b"x")
            self.assertEqual(existing_video_path(root, "123"), target)
