"""Report migration and publication tests; no network or Retool install required."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import automate


class ReportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def write(self, name, text="report"):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def test_migration_uses_retool_timestamp_across_dat_dates_not_mtime(self):
        old = self.write("Sony - PlayStation Portable (2026-10-27 19-12-34) (Retool 2026-10-28 08-27-03) (-y) report.txt", "old")
        new = self.write("Sony - PlayStation Portable (2026-08-20 20-18-36) (Retool 2026-10-30 08-38-28) (-y) report.txt", "new")
        os.utime(old, (2000000000, 2000000000))
        os.utime(new, (1000000000, 1000000000))
        self.assertEqual(automate.consolidate_reports(self.root, "redump"), 2)
        stable = self.root / "Sony - PlayStation Portable report.txt"
        self.assertEqual(stable.read_text(), "new")
        self.assertEqual(list(self.root.iterdir()), [stable])
        self.assertEqual(automate.consolidate_reports(self.root, "redump"), 0)

    def test_no_intro_migration_preserves_format_qualifiers(self):
        for kind in ("Headered", "Headerless"):
            self.write(f"Nintendo - Nintendo Entertainment System ({kind}) (20260806-082610) (Retool 2026-10-30 08-38-28) (-ly) report.txt", kind)
        automate.consolidate_reports(self.root, "no-intro")
        for kind in ("Headered", "Headerless"):
            self.assertEqual((self.root / f"Nintendo - Nintendo Entertainment System ({kind}) report.txt").read_text(), kind)

    def test_redump_datfile_variants_share_one_system(self):
        self.write("Sony - PlayStation - Datfile (serial,version) (10970) (2026-10-29 10-00-00) (Retool 2026-10-29 12-00-00) report.txt", "old")
        self.write("Sony - PlayStation (2026-10-30 10-00-00) (Retool 2026-10-30 12-00-00) report.txt", "new")
        self.assertEqual(automate.consolidate_reports(self.root, "redump"), 2)
        self.assertEqual((self.root / "Sony - PlayStation report.txt").read_text(), "new")

    def test_existing_stable_report_remains_authoritative(self):
        self.write("Sony - PlayStation report.txt", "stable")
        self.write("Sony - PlayStation (2026-10-30 10-00-00) (Retool 2026-10-30 12-00-00) report.txt", "legacy")
        self.write("notes.txt", "unrelated")
        self.assertEqual(automate.consolidate_reports(self.root, "redump"), 1)
        self.assertEqual((self.root / "Sony - PlayStation report.txt").read_text(), "stable")
        self.assertEqual((self.root / "notes.txt").read_text(), "unrelated")

    def test_migration_copy_failure_preserves_legacy_files(self):
        legacy = self.write("Sony - PlayStation (2026-10-30 10-00-00) (Retool 2026-10-30 12-00-00) report.txt", "legacy")
        with patch.object(automate.shutil, "copyfile", side_effect=OSError("copy failed")):
            self.assertEqual(automate.consolidate_reports(self.root, "redump"), 0)
        self.assertEqual(list(self.root.iterdir()), [legacy])

    def run_retool(self, *, returncode=0, dat=True, report=True, stdout="", fail_copy=False):
        input_dat = self.write("input/Sony - PlayStation (2026-10-30 10-00-00).dat", "input")
        retool = self.write("retool/retool.py")
        stable = self.write("reports/Sony - PlayStation report.txt", "previous")

        def process(command, **kwargs):
            output = Path(command[command.index("--output") + 1])
            if dat:
                (output / "generated.dat").write_text("new DAT")
            if report:
                (output / "generated report.txt").write_text("new report")
            return subprocess.CompletedProcess(command, returncode, stdout, "")

        with patch.object(automate.subprocess, "run", side_effect=process):
            if fail_copy:
                with patch.object(automate.shutil, "copyfile", side_effect=OSError("copy failed")):
                    result = automate.run_retool(input_dat, retool.parent, self.root / "dats", stable.parent, [], "", "redump", "McLean")
            else:
                result = automate.run_retool(input_dat, retool.parent, self.root / "dats", stable.parent, [], "", "redump", "McLean")
        self.assertFalse(any((self.root / "dats").glob("retool-*")))
        return result, stable

    def test_success_replaces_stable_report(self):
        result, stable = self.run_retool()
        self.assertEqual(result[2], "success")
        self.assertEqual(result[1], stable)
        self.assertEqual(stable.read_text(), "new report")

    def test_nonzero_exit_with_partial_outputs_preserves_previous(self):
        result, stable = self.run_retool(returncode=1)
        self.assertEqual(result[2], "failed")
        self.assertEqual(stable.read_text(), "previous")
        self.assertFalse(list((self.root / "dats").glob("*.dat")))

    def test_success_without_report_preserves_previous(self):
        result, stable = self.run_retool(report=False)
        self.assertEqual(result[2], "success")
        self.assertIsNone(result[1])
        self.assertEqual(stable.read_text(), "previous")

    def test_unknown_report_only_run_preserves_previous(self):
        result, stable = self.run_retool(dat=False)
        self.assertEqual(result[2], "failed")
        self.assertEqual(stable.read_text(), "previous")

    def test_valid_empty_result_can_publish_report(self):
        result, stable = self.run_retool(dat=False, stdout="No titles in the input DAT match your preferences")
        self.assertEqual(result[2], "not_required")
        self.assertEqual(stable.read_text(), "new report")

    def test_publication_copy_failure_preserves_previous(self):
        result, stable = self.run_retool(fail_copy=True)
        self.assertEqual(result[2], "failed")
        self.assertEqual(stable.read_text(), "previous")
        self.assertFalse(list(stable.parent.glob("*.tmp")))

    def test_configs_are_migrated_independently(self):
        for config in ("McLean", "PropeR"):
            legacy = self.write(f"{config}/redump/Sony - PlayStation (2026-10-30 10-00-00) (Retool 2026-10-30 12-00-00) report.txt", config)
            automate.consolidate_reports(legacy.parent, "redump")
        for config in ("McLean", "PropeR"):
            self.assertEqual((self.root / config / "redump/Sony - PlayStation report.txt").read_text(), config)


if __name__ == "__main__":
    unittest.main()

