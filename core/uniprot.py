"""
core/uniprot.py

Fetch a protein sequence from UniProt by accession.

Uses the UniProt REST API's plain-FASTA endpoint and the Python standard
library only (urllib) -- no third-party HTTP dependency. Network access
is isolated behind ``_http_get`` so the rest of the function can be
tested offline by monkeypatching it.
"""

import re
import urllib.error
import urllib.request

UNIPROT_FASTA_URL = "https://rest.uniprot.org/uniprotkb/{accession}.fasta"
_USER_AGENT = "protein-toolkit/0.1 (https://github.com/)"

# UniProtKB accessions are 6 or 10 alphanumerics, optionally followed by
# an isoform suffix like "-2". This is a cheap sanity guard; the real
# check is whether the API returns 404.
_ACCESSION_RE = re.compile(r"^[A-Z0-9]{6}([A-Z0-9]{4})?(-\d+)?$")


class UniProtError(RuntimeError):
    """Raised for any failure while fetching a UniProt sequence."""


def _http_get(url: str, timeout: float) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8")


def fetch_fasta(accession: str, timeout: float = 10.0) -> str:
    """
    Return the raw FASTA text for a UniProt accession (e.g. "P69905").

    The returned string still contains the ">" header line, so it can be
    dropped straight into the sequence calculator, which knows how to
    strip FASTA headers.

    Raises
    ------
    UniProtError
        On an empty/invalid accession, a 404 (accession not found), any
        other HTTP error, or a network failure.
    """
    accession = accession.strip().upper()
    if not accession:
        raise UniProtError("No accession provided.")
    if not _ACCESSION_RE.match(accession):
        raise UniProtError(f"'{accession}' does not look like a UniProt accession.")

    url = UNIPROT_FASTA_URL.format(accession=accession)
    try:
        text = _http_get(url, timeout)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise UniProtError(f"Accession '{accession}' not found in UniProt.") from exc
        raise UniProtError(f"UniProt returned HTTP {exc.code} for '{accession}'.") from exc
    except urllib.error.URLError as exc:
        raise UniProtError(
            f"Could not reach UniProt ({exc.reason}). Check your internet connection."
        ) from exc

    if not text.lstrip().startswith(">"):
        raise UniProtError(f"Unexpected (non-FASTA) response for '{accession}'.")
    return text
