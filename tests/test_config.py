import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from app import paths
from app.config import AppConfig


class ConfigTests(unittest.TestCase):
    def test_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            original = AppConfig(
                threshold_percent=2.5,
                tolerance=12,
                max_unchanged=8,
                save_folder=str(Path(tmp) / "shots"),
            )
            original.save(path)
            loaded = AppConfig.load(path)
            self.assertEqual(loaded, original)

    def test_missing_file_returns_defaults(self):
        with tempfile.TemporaryDirectory() as tmp:
            loaded = AppConfig.load(Path(tmp) / "nope.json")
            self.assertEqual(loaded.threshold_percent, 1.0)
            self.assertEqual(loaded.tolerance, 8)
            self.assertEqual(loaded.max_unchanged, 5)

    def test_broken_json_returns_defaults(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            path.write_text("{not json", encoding="utf-8")
            self.assertEqual(AppConfig.load(path).max_unchanged, 5)

    def test_default_output_folder_is_inside_program(self):
        config = AppConfig()
        self.assertEqual(config.resolved_save_folder(), paths.default_output_dir())
        self.assertEqual(config.resolved_save_folder().parent, paths.program_dir())

    def test_explicit_folder_wins(self):
        config = AppConfig(save_folder=r"D:\somewhere\shots")
        self.assertEqual(config.resolved_save_folder(), Path(r"D:\somewhere\shots"))

    def test_default_path_uses_data_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "data" / "config.json"
            with mock.patch.object(paths, "config_path", return_value=target):
                config = AppConfig(max_unchanged=7)
                written = config.save()
            self.assertEqual(written, target)
            self.assertTrue(target.exists())
            with mock.patch.object(paths, "config_path", return_value=target):
                self.assertEqual(AppConfig.load().max_unchanged, 7)

    def test_legacy_config_is_read_when_new_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            new_path = Path(tmp) / "data" / "config.json"
            legacy = Path(tmp) / "legacy.json"
            legacy.write_text(
                json.dumps({"max_unchanged": 9, "save_folder": str(Path(tmp) / "old")}),
                encoding="utf-8",
            )
            with mock.patch.object(paths, "config_path", return_value=new_path), mock.patch.object(
                paths, "legacy_config_path", return_value=legacy
            ):
                loaded = AppConfig.load()
            self.assertEqual(loaded.max_unchanged, 9)
            self.assertEqual(loaded.save_folder, str(Path(tmp) / "old"))


    def test_audio_fields_default_off(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            path.write_text(json.dumps({"max_unchanged": 3}), encoding="utf-8")
            loaded = AppConfig.load(path)
            self.assertFalse(loaded.audio_enabled)
            self.assertEqual(loaded.audio_device_id, "")
            self.assertEqual(loaded.audio_device_name, "")
            self.assertAlmostEqual(loaded.audio_tolerance_db, 1.5)

    def test_audio_fields_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            config = AppConfig(
                audio_enabled=True,
                audio_device_id="{0.0.0.00000000}.{abc}",
                audio_device_name="扬声器",
                audio_tolerance_db=2.5,
            )
            config.save(path)
            loaded = AppConfig.load(path)
            self.assertTrue(loaded.audio_enabled)
            self.assertEqual(loaded.audio_device_id, "{0.0.0.00000000}.{abc}")
            self.assertEqual(loaded.audio_device_name, "扬声器")
            self.assertAlmostEqual(loaded.audio_tolerance_db, 2.5)

    def test_agent_fields_default_and_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            defaults = AppConfig()
            self.assertFalse(defaults.agent_enabled)
            self.assertEqual(defaults.agent_base_url, "")
            self.assertEqual(defaults.agent_session_id, "")
            self.assertEqual(defaults.agent_timeout_ms, 300_000)

            config = AppConfig(
                agent_enabled=True,
                agent_base_url="http://127.0.0.1:56193/conversation-api",
                agent_session_id="session-abc",
                agent_timeout_ms=120_000,
            )
            config.save(path)
            loaded = AppConfig.load(path)
            self.assertTrue(loaded.agent_enabled)
            self.assertEqual(loaded.agent_base_url, config.agent_base_url)
            self.assertEqual(loaded.agent_session_id, "session-abc")
            self.assertEqual(loaded.agent_timeout_ms, 120_000)


if __name__ == "__main__":
    unittest.main()
