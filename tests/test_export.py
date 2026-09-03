"""
Tests for the export helpers in gui.app (_write_table etc.).

Importing gui.app pulls in tkinter and matplotlib; if that is not
available the whole module is skipped rather than failing.

Run with: python -m unittest discover -s tests
"""

import csv
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from gui.app import _BATCH_COLUMNS, _column_heading, _write_table

    _GUI_IMPORTABLE = True
except Exception:  # noqa: BLE001 - tkinter/matplotlib may be missing
    _GUI_IMPORTABLE = False


@unittest.skipUnless(_GUI_IMPORTABLE, "gui.app (tkinter/matplotlib) not importable")
class TestWriteTable(unittest.TestCase):
    def test_csv_writes_header_and_rows(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "out.csv")
            _write_table(path, ["a", "b"], [[1, 2], ["x", "y"]])
            with open(path) as handle:
                rows = list(csv.reader(handle))
        self.assertEqual(rows[0], ["a", "b"])
        self.assertEqual(rows[1], ["1", "2"])
        self.assertEqual(rows[2], ["x", "y"])

    def test_xlsx_is_centered_with_frozen_header(self):
        try:
            from openpyxl import load_workbook
        except ImportError:
            self.skipTest("openpyxl not installed")
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "out.xlsx")
            _write_table(path, ["prop", "value"], [["length", 20], ["pI", 9.7]])
            sheet = load_workbook(path).active
        self.assertEqual(sheet["A1"].value, "prop")
        self.assertTrue(sheet["A1"].font.bold)
        self.assertEqual(sheet["A1"].alignment.horizontal, "center")
        self.assertEqual(sheet["B2"].alignment.horizontal, "center")
        self.assertEqual(sheet.freeze_panes, "A2")

    def test_every_batch_column_has_a_heading(self):
        for column in _BATCH_COLUMNS:
            self.assertTrue(_column_heading(column))


if __name__ == "__main__":
    unittest.main()
