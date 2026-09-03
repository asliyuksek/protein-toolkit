"""
Tests for core.fasta.parse_fasta.

Run with: python -m unittest discover -s tests
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.fasta import parse_fasta


class TestParseFasta(unittest.TestCase):
    def test_single_raw_sequence_no_header(self):
        records = parse_fasta("MVLSPADK\nTNVKAAWGK")
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].record_id, "seq1")
        self.assertEqual(records[0].description, "")
        self.assertEqual(records[0].sequence, "MVLSPADKTNVKAAWGK")

    def test_multiple_records_split_and_id_parsed(self):
        text = (
            ">sp|P69905|HBA_HUMAN Hemoglobin subunit alpha\n"
            "MVLSPADKTNV\nKAAWGKVGA\n"
            ">sp|P68871|HBB_HUMAN Hemoglobin subunit beta\n"
            "MVHLTPEEKSAVTALWGKV\n"
        )
        records = parse_fasta(text)
        self.assertEqual(len(records), 2)
        self.assertEqual(records[0].record_id, "sp|P69905|HBA_HUMAN")
        self.assertEqual(records[0].description, "Hemoglobin subunit alpha")
        self.assertEqual(records[0].sequence, "MVLSPADKTNVKAAWGKVGA")
        self.assertEqual(records[1].record_id, "sp|P68871|HBB_HUMAN")
        self.assertEqual(records[1].sequence, "MVHLTPEEKSAVTALWGKV")

    def test_blank_lines_and_whitespace_ignored(self):
        text = ">a\n\nMVLS  \n\n  PADK\n>b\nAAAA\n"
        records = parse_fasta(text)
        self.assertEqual([r.record_id for r in records], ["a", "b"])
        self.assertEqual(records[0].sequence, "MVLSPADK")

    def test_empty_input_returns_no_records(self):
        self.assertEqual(parse_fasta("   \n  \n"), [])

    def test_header_with_no_description(self):
        records = parse_fasta(">justanid\nMVLS")
        self.assertEqual(records[0].record_id, "justanid")
        self.assertEqual(records[0].description, "")


if __name__ == "__main__":
    unittest.main()
