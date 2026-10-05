"""Portable tests for the deletion boundary and accounting primitives."""
from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from asxels_cleaner.engine import Target, TargetKind, clean_targets, human_bytes, scan_targets


class CleanupEngineTests(unittest.TestCase):
    def test_contents_target_preserves_its_container(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "cache"
            root.mkdir()
            (root / "old.tmp").write_bytes(b"abc")
            target = Target(root, TargetKind.CONTENTS, root, "test")
            result = clean_targets([target])
            self.assertTrue(root.is_dir())
            self.assertFalse((root / "old.tmp").exists())
            self.assertEqual(result.bytes_removed, 3)
            self.assertEqual(result.files_removed, 1)

    def test_file_target_deletes_only_the_explicit_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            cache = root / "thumbcache.db"
            personal = root / "important.txt"
            cache.write_bytes(b"cache")
            personal.write_bytes(b"keep")
            clean_targets([Target(cache, TargetKind.FILE, root, "test")])
            self.assertFalse(cache.exists())
            self.assertTrue(personal.exists())

    def test_path_outside_boundary_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            boundary = base / "cache"
            boundary.mkdir()
            outside = base / "personal.txt"
            outside.write_text("keep", encoding="utf-8")
            result = clean_targets([Target(outside, TargetKind.FILE, boundary, "unsafe")])
            self.assertTrue(outside.exists())
            self.assertEqual(result.errors, 1)

    def test_cancellation_preserves_remaining_files(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "cache"
            root.mkdir()
            remaining = root / "stay.tmp"
            remaining.write_bytes(b"keep")
            result = clean_targets([Target(root, TargetKind.CONTENTS, root, "test")], cancel=lambda: True)
            self.assertTrue(result.cancelled)
            self.assertTrue(remaining.exists())

    def test_scan_reports_exact_file_size(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "cache"
            root.mkdir()
            (root / "a.tmp").write_bytes(b"12345")
            report = scan_targets([Target(root, TargetKind.CONTENTS, root, "test")])
            self.assertEqual(report.bytes_found, 5)
            self.assertEqual(report.items_found, 1)

    def test_human_bytes_is_readable(self) -> None:
        self.assertEqual(human_bytes(0), "0 B")
        self.assertEqual(human_bytes(1024), "1.0 KB")


if __name__ == "__main__":
    unittest.main()
