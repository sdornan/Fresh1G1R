"""Regression coverage for Redump catalog identity and version cleanup."""
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import automate


class DatCleanupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def dat(self, name, version, processing_date="2026-11-01 12-00-00"):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f'<datafile><header><version>{version}</version><date>{processing_date}</date></header><game name="Test"/></datafile>', encoding="utf-8")
        return path

    def test_redump_names_have_one_identity(self):
        names = [
            "IBM - PC compatible - Datfile (serial,version) (60311) (2026-08-12 02-06-54)",
            "IBM - PC compatible - Datfile (62045) (2026-11-01 08-48-06)",
            "IBM - PC compatible - Datfile (serial,version) (60311) (Redump - Fresh1G1R - McLean)",
            "IBM - PC compatible (Redump - Fresh1G1R - McLean)",
        ]
        for name in names:
            with self.subTest(name=name):
                self.assertEqual(automate.extract_system_name(name, "redump"), "IBM - PC compatible")

    def test_input_cleanup_uses_source_version_not_count_or_mtime(self):
        old = self.dat("IBM - PC compatible - Datfile (serial,version) (99999) (2026-08-12 02-06-54).dat", "2026-08-12 02-06-54")
        new = self.dat("IBM - PC compatible - Datfile (62045) (2026-11-01 08-48-06).dat", "2026-11-01 08-48-06")
        os.utime(old, (2000000000, 2000000000))
        os.utime(new, (1000000000, 1000000000))
        self.assertEqual(automate.consolidate_dats(self.root, "redump"), 1)
        self.assertEqual(list(self.root.iterdir()), [new])
        self.assertEqual(automate.consolidate_dats(self.root, "redump"), 0)

    def test_processed_header_version_beats_filename_count_and_processing_date(self):
        legacy = self.dat("IBM - PC compatible - Datfile (serial,version) (60311) (Redump - Fresh1G1R - McLean).dat", "2026-11-01 08-48-06", "2026-11-01 09-00-00")
        stable = self.dat("IBM - PC compatible (Redump - Fresh1G1R - McLean).dat", "2026-10-01 08-48-06", "2026-11-02 09-00-00")
        content = legacy.read_text()
        automate.save_metadata(self.root, {"IBM - PC compatible - Datfile (serial,version) (60311)": {"input_filename": "latest-input.dat", "output_path": legacy.name}, "IBM - PC compatible": {"input_filename": "old-input.dat", "output_path": stable.name}, "Other system": {"input_filename": "other.dat", "output_path": "other.dat"}})
        self.assertEqual(automate.consolidate_dats(self.root, "redump", "McLean"), 1)
        self.assertEqual(stable.read_text(), content)
        metadata = automate.load_metadata(self.root)
        self.assertEqual(metadata["IBM - PC compatible"], {"input_filename": "latest-input.dat", "output_path": stable.name})
        self.assertNotIn("IBM - PC compatible - Datfile (serial,version) (60311)", metadata)
        self.assertIn("Other system", metadata)

    def test_unknown_version_keeps_entire_group(self):
        old = self.dat("IBM - PC compatible - Datfile (serial,version) (60311) (Redump - Fresh1G1R - McLean).dat", "unknown")
        new = self.dat("IBM - PC compatible (Redump - Fresh1G1R - McLean).dat", "2026-11-01 08-48-06")
        self.assertEqual(automate.consolidate_dats(self.root, "redump", "McLean"), 0)
        self.assertTrue(old.exists() and new.exists())

    def test_unreadable_header_keeps_entire_group(self):
        old = self.dat("IBM - PC compatible - Datfile (serial,version) (60311) (Redump - Fresh1G1R - McLean).dat", "2026-08-12 02-06-54")
        new = self.root / "IBM - PC compatible (Redump - Fresh1G1R - McLean).dat"
        new.write_text("<broken>")
        self.assertEqual(automate.consolidate_dats(self.root, "redump", "McLean"), 0)
        self.assertTrue(old.exists() and new.exists())

    def test_failed_promotion_keeps_both_versions(self):
        legacy = self.dat("IBM - PC compatible - Datfile (serial,version) (60311) (Redump - Fresh1G1R - McLean).dat", "2026-11-01 08-48-06")
        stable = self.dat("IBM - PC compatible (Redump - Fresh1G1R - McLean).dat", "2026-10-01 08-48-06")
        previous = stable.read_text()
        with patch.object(automate.shutil, "copyfile", side_effect=OSError("copy failed")):
            self.assertEqual(automate.consolidate_dats(self.root, "redump", "McLean"), 0)
        self.assertTrue(legacy.exists())
        self.assertEqual(stable.read_text(), previous)

    def test_equal_source_version_prefers_stable_filename(self):
        self.dat("IBM - PC compatible - Datfile (serial,version) (60311) (Redump - Fresh1G1R - McLean).dat", "2026-11-01 08-48-06")
        stable = self.dat("IBM - PC compatible (Redump - Fresh1G1R - McLean).dat", "2026-11-01 08-48-06")
        self.assertEqual(automate.consolidate_dats(self.root, "redump", "McLean"), 1)
        self.assertEqual(list(self.root.iterdir()), [stable])

    def test_no_intro_format_variants_remain_separate(self):
        for kind in ("Headered", "Headerless"):
            self.dat(f"Nintendo - Nintendo Entertainment System ({kind}) (20260806-082610).dat", "20260806-082610")
            self.dat(f"Nintendo - Nintendo Entertainment System ({kind}) (20261101-082610).dat", "20261101-082610")
        self.assertEqual(automate.consolidate_dats(self.root, "no-intro"), 2)
        self.assertEqual(len(list(self.root.glob("*.dat"))), 2)

    def test_configurations_and_other_systems_remain_separate(self):
        for config in ("McLean", "PropeR", "Hearto"):
            self.dat(f"{config}/IBM - PC compatible - Datfile (serial,version) (60311) (Redump - Fresh1G1R - {config}).dat", "2026-08-12 02-06-54")
            self.dat(f"{config}/IBM - PC compatible (Redump - Fresh1G1R - {config}).dat", "2026-11-01 08-48-06")
        other = self.dat("McLean/Sony - PlayStation (Redump - Fresh1G1R - McLean).dat", "2026-08-12 02-06-54")
        automate.consolidate_dats(self.root / "McLean", "redump", "McLean")
        self.assertEqual(len(list((self.root / "McLean").glob("*.dat"))), 2)
        self.assertEqual(len(list((self.root / "PropeR").glob("*.dat"))), 2)
        self.assertEqual(len(list((self.root / "Hearto").glob("*.dat"))), 2)
        self.assertTrue(other.exists())


if __name__ == "__main__":
    unittest.main()

