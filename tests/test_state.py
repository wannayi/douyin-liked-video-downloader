import tempfile
import unittest
from pathlib import Path

from douyin_likes_downloader.state import DownloadState, load_state, save_state


class StateTests(unittest.TestCase):
    def test_state_round_trip_and_atomic_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            video_path = root / "downloads" / "123_video.mp4"
            video_path.parent.mkdir()
            video_path.write_bytes(b"valid video")
            state_path = root / "data" / "state.json"
            state = DownloadState()
            state.mark_downloaded("123", video_path, "标题")
            state.initialized = True
            save_state(state_path, state)

            loaded = load_state(state_path)
            self.assertTrue(loaded.initialized)
            self.assertTrue(loaded.is_downloaded("123"))
            self.assertEqual(loaded.downloaded["123"].title, "标题")
            self.assertFalse(any(path.suffix == ".tmp" for path in state_path.parent.iterdir()))

    def test_missing_file_is_not_considered_downloaded(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            state = DownloadState()
            state.mark_downloaded("123", Path(temp_dir) / "missing.mp4")
            self.assertFalse(state.is_downloaded("123"))

