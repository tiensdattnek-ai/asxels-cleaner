"""Tests for the bounded deletion primitives (run with: python -m unittest)."""
import tempfile
import unittest
from pathlib import Path

import main


class CleanerSafetyTests(unittest.TestCase):
    def test_contents_target_keeps_the_container(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "safe-cache"
            root.mkdir()
            (root / "old.tmp").write_bytes(b"abc")
            report = main.clean_targets([main.Target(root, True)])
            self.assertTrue(root.is_dir())
            self.assertFalse((root / "old.tmp").exists())
            self.assertEqual(report.bytes_removed, 3)

    def test_file_target_deletes_only_the_explicit_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            first = root / "thumbcache_1.db"
            second = root / "important.txt"
            first.write_bytes(b"cache")
            second.write_bytes(b"keep")
            main.clean_targets([main.Target(first, False)])
            self.assertFalse(first.exists())
            self.assertTrue(second.exists())

    def test_duplicate_targets_are_collapsed(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            result = main._dedupe_targets([main.Target(root, True), main.Target(root, True)])
            self.assertEqual(len(result), 1)

    def test_human_bytes_is_readable(self):
        self.assertEqual(main.human_bytes(0), "0 B")
        self.assertEqual(main.human_bytes(1024), "1.0 KB")


if __name__ == "__main__":
    unittest.main()
