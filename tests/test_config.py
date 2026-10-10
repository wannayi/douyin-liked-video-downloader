import json
import tempfile
import unittest
from pathlib import Path

from douyin_likes_downloader.config import ConfigError, load_config


class ConfigTests(unittest.TestCase):
    def test_relative_paths_are_based_on_config_directory(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config_path = root / "nested" / "config.json"
            config_path.parent.mkdir()
            config_path.write_text(
                json.dumps({"output_dir": "videos", "data_dir": "runtime"}),
                encoding="utf-8",
            )
            config = load_config(config_path)
            self.assertEqual(config.output_dir, config_path.parent.resolve() / "videos")
            self.assertEqual(config.data_dir, config_path.parent.resolve() / "runtime")
            self.assertEqual(config.schedule_time, "05:00")

    def test_invalid_schedule_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "config.json"
            path.write_text(json.dumps({"schedule_time": "25:00"}), encoding="utf-8")
            with self.assertRaises(ConfigError):
                load_config(path)
