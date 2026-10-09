# This module provides split with no external dependencies.

from dataclasses import dataclass
from typing import List

@dataclass
class FastaRec:
    record_id: str
    description: str
    sequence: str

def parse_fasta(text: str) -> List[FastaRec]:
    # Split raw text into FASTA records.
    records: List[FastaRec] = []
    header: str | None = None
    description = ""
    chunks: List[str] = []

    def flush() -> None:
        if header is None and not chunks:
            return
        sequence = "".join(chunks)
        if header is None:
            records.append(FastaRec("seq1", "", sequence))
        else:
            records.append(FastaRec(header, description, sequence))

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
