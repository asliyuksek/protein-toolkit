"""
Basic sanity tests for core.sequence_props.

Run with: python -m unittest discover -s tests
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.sequence_props import (
    MultipleRecordsError,
    calculate_properties,
    clean_sequence,
)


class TestCleanSequence(unittest.TestCase):
    def test_strips_fasta_header(self):
        raw = ">sp|P69905|HBA_HUMAN\nMVLSPADKTNVKAAWGKVGA"
        seq, warnings = clean_sequence(raw)
        self.assertFalse(seq.startswith(">"))
        self.assertTrue(seq.startswith("MVLSPADK"))

    def test_flags_nonstandard_residues(self):
        seq, warnings = clean_sequence("MVLSPADKXZB")
        self.assertTrue(any("Non-standard" in w for w in warnings))

    def test_empty_sequence_raises(self):
        with self.assertRaises(ValueError):
            calculate_properties(">header only\n")


class TestCalculateProperties(unittest.TestCase):
    def setUp(self):
        # First 20 residues of human hemoglobin alpha chain (UniProt P69905)
        self.hba_fragment = "MVLSPADKTNVKAAWGKVGA"

    def test_known_sequence_reasonable_ranges(self):
        result = calculate_properties(self.hba_fragment)
        self.assertEqual(result.length, 20)
        self.assertGreater(result.molecular_weight_da, 0)
        self.assertTrue(0 <= result.isoelectric_point <= 14)
        self.assertAlmostEqual(sum(result.amino_acid_percent.values()), 1.0, places=2)

    def test_cys_count_matches_sequence(self):
        result = calculate_properties("MCCCK")
        self.assertEqual(result.cys_count, 3)

    def test_instability_verdict_threshold(self):
        result = calculate_properties(self.hba_fragment)
        expected = "Likely stable" if result.instability_index <= 40 else "Likely unstable"
        self.assertEqual(result.instability_verdict, expected)

    def test_nonstandard_residues_do_not_crash(self):
        # Regression test: X/Z/B previously reached Biopython's
        # instability_index() unfiltered and raised an unhandled
        # KeyError. They must now be excluded from analysis (with a
        # warning) instead of crashing the calculation.
        result = calculate_properties("MVLSPADKXZB")
        self.assertEqual(result.length, 11)  # full input length
        self.assertGreater(result.molecular_weight_da, 0)
        self.assertTrue(any("Non-standard" in w for w in result.warnings))

    def test_all_nonstandard_residues_raises(self):
        with self.assertRaises(ValueError):
            calculate_properties("XXXBBBZZZ")

    def test_aliphatic_index_pure_alanine(self):
        # mol% Ala = 100, everything else 0 -> AI = 100
        result = calculate_properties("A" * 12)
        self.assertAlmostEqual(result.aliphatic_index, 100.0, places=4)

    def test_aliphatic_index_pure_valine(self):
        # mol% Val = 100 -> AI = 2.9 * 100 = 290
        result = calculate_properties("V" * 12)
        self.assertAlmostEqual(result.aliphatic_index, 290.0, places=4)

    def test_molecular_formula_dipeptide(self):
        # Gly-Gly: 2 x residue C2H3NO + one water (H2O) = C4H8N2O3
        result = calculate_properties("GG")
        self.assertEqual(result.molecular_formula, "C4H8N2O3")
        self.assertEqual(
            result.atom_counts, {"C": 4, "H": 8, "N": 2, "O": 3, "S": 0}
        )
        self.assertEqual(result.total_atoms, 17)

    def test_atom_counts_sum_to_total(self):
        result = calculate_properties(self.hba_fragment)
        self.assertEqual(sum(result.atom_counts.values()), result.total_atoms)

    def test_formula_mass_matches_biopython_mw(self):
        # Mass rebuilt from the atom counts should agree with Biopython's
        # molecular_weight() to well within a Dalton.
        result = calculate_properties(self.hba_fragment)
        avg_atomic = {
            "C": 12.0107,
            "H": 1.00794,
            "N": 14.0067,
            "O": 15.9994,
            "S": 32.065,
        }
        formula_mass = sum(
            avg_atomic[element] * count for element, count in result.atom_counts.items()
        )
        self.assertAlmostEqual(formula_mass, result.molecular_weight_da, delta=0.5)

    def test_formula_omits_sulfur_when_absent(self):
        result = calculate_properties("GG")
        self.assertNotIn("S", result.molecular_formula)
        self.assertEqual(result.atom_counts["S"], 0)

    def test_multiple_fasta_records_rejected(self):
        two_records = ">chainA\nMVLSPADKTNVKAAWGKVGA\n>chainB\nMVHLTPEEKSAVTALWGKV\n"
        with self.assertRaises(MultipleRecordsError):
            calculate_properties(two_records)

    def test_multiple_records_error_is_a_valueerror(self):
        with self.assertRaises(ValueError):
            calculate_properties(">a\nMVLS\n>b\nKKEE\n")

    def test_single_fasta_record_still_accepted(self):
        result = calculate_properties(">sp|P69905|HBA desc line\nMVLSPADKTNVKAAWGKVGA\n")
        self.assertEqual(result.length, 20)


if __name__ == "__main__":
    unittest.main()
