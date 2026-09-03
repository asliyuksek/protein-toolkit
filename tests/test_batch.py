"""
Tests for core.sequence_props.calculate_batch.

Run with: python -m unittest discover -s tests
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.sequence_props import calculate_batch


class TestCalculateBatch(unittest.TestCase):
    def test_multiple_records_each_get_properties(self):
        text = (
            ">alpha\nMVLSPADKTNVKAAWGKVGA\n"
            ">beta\nMVHLTPEEKSAVTALWGKV\n"
        )
        results = calculate_batch(text)
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0].record_id, "alpha")
        self.assertIsNotNone(results[0].properties)
        self.assertIsNone(results[0].error)
        self.assertEqual(results[0].properties.length, 20)

    def test_bad_record_is_captured_not_raised(self):
        text = (
            ">good\nMVLSPADKTNVKAAWGKVGA\n"
            ">bad\nXXXXZZZZBBBB\n"
        )
        results = calculate_batch(text)
        self.assertEqual(len(results), 2)
        self.assertIsNone(results[1].properties)
        self.assertIsNotNone(results[1].error)
        # the good record before it still succeeded
        self.assertIsNotNone(results[0].properties)

    def test_empty_input_returns_empty_list(self):
        self.assertEqual(calculate_batch("   "), [])

    def test_raw_paste_without_header_is_one_record(self):
        results = calculate_batch("MVLSPADKTNVKAAWGKVGA")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].record_id, "seq1")
        self.assertEqual(results[0].properties.length, 20)

    def test_multi_record_input_is_not_rejected_in_batch(self):
        # the single-sequence MultipleRecordsError guard must not leak into
        # batch: each record here is handed to calculate_properties alone.
        results = calculate_batch(
            ">a\nMVLSPADKTNVKAAWGKVGA\n>b\nMVHLTPEEKSAVTALWGKV\n>c\nGGGGSSSS\n"
        )
        self.assertEqual(len(results), 3)
        self.assertTrue(all(r.error is None for r in results))


if __name__ == "__main__":
    unittest.main()
