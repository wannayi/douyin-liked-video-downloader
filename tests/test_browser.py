import unittest

from douyin_likes_downloader.browser import _media_urls_from_html, _select_media_source, video_items_from_records
from douyin_likes_downloader.browser import MediaSource


class BrowserPureFunctionTests(unittest.TestCase):
    def test_video_records_are_normalized_and_deduplicated(self):
        records = [
            {"url": "/video/100", "description": "第一"},
            {"url": "https://www.douyin.com/video/100?foo=1", "description": "重复"},
            {"url": "/video/200", "description": "第二", "author": "作者"},
            {"url": "/user/abc", "description": "不是视频"},
        ]
        items = video_items_from_records(records, "https://www.douyin.com/user/self")
        self.assertEqual([item.video_id for item in items], ["100", "200"])
        self.assertEqual(items[1].author, "作者")

    def test_media_html_urls_and_ranking(self):
        html = '"https://cdn.test/avatar.jpg" "https://cdn.test/playwm/video.mp4"'
        urls = _media_urls_from_html(html)
        selected = _select_media_source(
            [MediaSource(url=urls[0]), MediaSource(url="https://cdn.test/video.mp4", content_type="video/mp4")]
        )
        self.assertEqual(selected.url, "https://cdn.test/video.mp4")

