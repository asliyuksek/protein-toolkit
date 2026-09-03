"""
Tests for core.uniprot.fetch_fasta.

Network access is stubbed out via core.uniprot._http_get, so these tests
run offline and deterministically.

Run with: python -m unittest discover -s tests
"""

import os
import sys
import unittest
import urllib.error

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import uniprot
from core.uniprot import UniProtError, fetch_fasta

_SAMPLE_FASTA = (
    ">sp|P69905|HBA_HUMAN Hemoglobin subunit alpha OS=Homo sapiens\n"
    "MVLSPADKTNVKAAWGKVGAHAGEYGAEALERMFLSFPTTKTYFPHF\n"
)


class TestFetchFasta(unittest.TestCase):
    def setUp(self):
        self._real_http_get = uniprot._http_get
        self.calls = []

    def tearDown(self):
        uniprot._http_get = self._real_http_get

    def _stub(self, response=None, exc=None):
        def fake_http_get(url, timeout):
            self.calls.append((url, timeout))
            if exc is not None:
                raise exc
            return response

        uniprot._http_get = fake_http_get

    def test_builds_expected_url_and_returns_fasta(self):
        self._stub(response=_SAMPLE_FASTA)
        text = fetch_fasta("p69905")  # lower-case on purpose
        self.assertEqual(text, _SAMPLE_FASTA)
        self.assertEqual(
            self.calls[0][0], "https://rest.uniprot.org/uniprotkb/P69905.fasta"
        )

    def test_rejects_implausible_accession_without_network_call(self):
        self._stub(response=_SAMPLE_FASTA)
        with self.assertRaises(UniProtError):
            fetch_fasta("not-an-accession!")
        self.assertEqual(self.calls, [])

    def test_empty_accession_raises(self):
        self._stub(response=_SAMPLE_FASTA)
        with self.assertRaises(UniProtError):
            fetch_fasta("   ")

    def test_404_becomes_not_found_error(self):
        self._stub(
            exc=urllib.error.HTTPError(
                url="x", code=404, msg="Not Found", hdrs=None, fp=None
            )
        )
        with self.assertRaises(UniProtError) as ctx:
            fetch_fasta("A0A000")
        self.assertIn("not found", str(ctx.exception).lower())

    def test_network_failure_becomes_uniprot_error(self):
        self._stub(exc=urllib.error.URLError("no route to host"))
        with self.assertRaises(UniProtError):
            fetch_fasta("P69905")

    def test_non_fasta_response_raises(self):
        self._stub(response="<html>Service unavailable</html>")
        with self.assertRaises(UniProtError):
            fetch_fasta("P69905")


if __name__ == "__main__":
    unittest.main()
