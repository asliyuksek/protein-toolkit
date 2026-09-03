"""
core/fasta.py

Minimal multi-record FASTA parser.

core.sequence_props.clean_sequence() deliberately merges everything it is
given into one sequence (it strips *all* header lines), which is the right
behaviour for the single-sequence calculator. Batch processing needs the
opposite: keep each record separate. This module provides that split with
no external dependencies.
"""

from dataclasses import dataclass
from typing import List


@dataclass
class FastaRecord:
    record_id: str
    description: str
    sequence: str


def parse_fasta(text: str) -> List[FastaRecord]:
    """
    Split raw text into FASTA records.

    - Each ">" line starts a new record. The first whitespace-delimited
      token after ">" becomes ``record_id``; the remainder becomes
      ``description``.
    - A leading block of sequence lines with no ">" header (i.e. a plain
      raw-sequence paste) is returned as a single record with id "seq1".
    - Blank lines are ignored; residue lines are concatenated verbatim
      (not uppercased or validated here -- calculate_properties handles
      that downstream).
    """
    records: List[FastaRecord] = []
    header: str | None = None
    description = ""
    chunks: List[str] = []

    def flush() -> None:
        if header is None and not chunks:
            return
        sequence = "".join(chunks)
        if header is None:
            records.append(FastaRecord("seq1", "", sequence))
        else:
            records.append(FastaRecord(header, description, sequence))

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith(">"):
            flush()
            chunks = []
            body = line[1:].strip()
            parts = body.split(None, 1)
            header = parts[0] if parts else f"seq{len(records) + 1}"
            description = parts[1] if len(parts) > 1 else ""
        else:
            chunks.append(line)
    flush()
    return records
