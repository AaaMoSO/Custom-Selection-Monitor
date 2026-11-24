import unittest
from pathlib import Path

from app import paths


class PathsTests(unittest.TestCase):
    def test_program_dir_is_project_root(self):
        self.assertTrue((paths.program_dir() / "app").is_dir())
        self.assertTrue((paths.program_dir() / "run.py").is_file())

    def test_data_dir_lives_inside_program(self):
        self.assertEqual(paths.data_dir().name, "data")
        self.assertTrue(paths.data_dir().is_dir())
        self.assertEqual(paths.data_dir().parent.resolve(), paths.program_dir().resolve())

    def test_cache_dir_is_frames_subdir(self):
        self.assertEqual(paths.cache_dir(), paths.data_dir() / "frames")

    def test_default_output_dir(self):
        self.assertEqual(paths.default_output_dir(), paths.program_dir() / "captures")

    def test_config_path(self):
        self.assertEqual(paths.config_path(), paths.data_dir() / "config.json")

    def test_relative_to_program(self):
        relative = paths.relative_to_program(paths.cache_dir())
        self.assertEqual(Path(relative), Path("data") / "frames")

    def test_relative_falls_back_for_outside_paths(self):
        outside = Path("C:/Windows/System32")
        self.assertEqual(paths.relative_to_program(outside), str(outside))


if __name__ == "__main__":
    unittest.main()
