"""
Sequence-based protein property calculators.
This module has no GUI dependencies, so it can be reused directly
from a CLI, a notebook, a web app, or a test suite.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
from Bio.SeqUtils.ProtParam import ProteinAnalysis
from core.fasta import parse_fasta

set_AA = set("ACDEFGHIKLMNPQRSTVWY")

# Atom counts (C, H, N, O, S) for each amino acid *residue* -- i.e. the
# free amino acid minus one water molecule, which is what remains once
# the residue is joined into a peptide chain. Summing these over a
# sequence and adding one water back (for the free alpha-amino and
# alpha-carboxyl groups at the two termini) gives the molecular formula
# of the whole polypeptide.
res_atoms: Dict[str, Tuple[int, int, int, int, int]] = {
    "A": (3, 5, 1, 1, 0),
    "R": (6, 12, 4, 1, 0),
    "N": (4, 6, 2, 2, 0),
    "D": (4, 5, 1, 3, 0),
    "C": (3, 5, 1, 1, 1),
    "Q": (5, 8, 2, 2, 0),
    "E": (5, 7, 1, 3, 0),
    "G": (2, 3, 1, 1, 0),
    "H": (6, 7, 3, 1, 0),
    "I": (6, 11, 1, 1, 0),
    "L": (6, 11, 1, 1, 0),
    "K": (6, 12, 2, 1, 0),
    "M": (5, 9, 1, 1, 1),
    "F": (9, 9, 1, 1, 0),
    "P": (5, 7, 1, 1, 0),
    "S": (3, 5, 1, 2, 0),
    "T": (4, 7, 1, 2, 0),
    "W": (11, 10, 2, 1, 0),
    "Y": (9, 9, 1, 2, 0),
    "V": (5, 9, 1, 1, 0),
}

class MultiRecErr(ValueError):
    """
    Raised by calculate_properties() when the input holds more than one
    FASTA record. Single-sequence analysis would silently concatenate the
    chains into one polypeptide, which gives a wrong molecular weight, pI
    and formula (one set of termini instead of one per chain). Multi-record
    input belongs in calculate_batch() instead.

    Subclasses ValueError so existing ``except ValueError`` handlers still
    catch it.
    """

def count_fasta_headers(raw_sequence: str) -> int:
    return sum(1 for line in raw_sequence.splitlines() if line.lstrip().startswith(">"))

def clean_sequence(raw_sequence: str) -> Tuple[str, List[str]]:
    """
    Normalize a pasted or FASTA-derived sequence string.

    - Strips a leading FASTA header line (starting with '>') if present
    - Removes whitespace/newlines
    - Uppercases all residues
    - Flags non-standard amino acid letters (e.g. X, B, Z, U, O) instead
      of silently ignoring them, since their presence affects how much
      you should trust the downstream calculations.

    Returns
    -------
    (cleaned_sequence, warnings)
    """
    warnings: List[str] = []
    lines = [ln.strip() for ln in raw_sequence.strip().splitlines() if ln.strip()]
    lines = [ln for ln in lines if not ln.startswith(">")]
    sequence = "".join(lines).upper().replace(" ", "")

    non_standard = sorted(set(sequence) - set_AA)
    if non_standard:
        excluded_count = sum(sequence.count(ch) for ch in non_standard)
        warnings.append(
            "Non-standard residue letters found: "
            + ", ".join(non_standard)
            + f" ({excluded_count} residue(s), e.g. ambiguity codes X/B/Z or "
            "selenocysteine U). Biopython's physicochemical calculations "
            "(pI, MW, GRAVY, instability index, etc.) cannot handle these "
            "and would raise an error, so they are excluded from those "
            "calculations only. 'Length' below still reflects the full "
            "sequence you entered."
        )
    return sequence, warnings

@dataclass
class SequenceProperties:
    length: int
    molecular_weight_da: float
    isoelectric_point: float
    gravy: float
    instability_index: float
    instability_verdict: str
    aromaticity: float
    charge_at_ph7: float
    cys_count: int
    extinction_coeff_reduced: float
    extinction_coeff_oxidized: float
    aliphatic_index: float
    molecular_formula: str
    atom_counts: Dict[str, int]
    total_atoms: int
    secondary_structure_fraction: Dict[str, float]
    amino_acid_percent: Dict[str, float]
    warnings: List[str] = field(default_factory=list)

def aa_fracs(analysis: ProteinAnalysis) -> Dict[str, float]:
    """
    Return amino acid composition as fractions (0-1) that sum to ~1.0.

    Biopython's API for this has changed across versions: older
    releases expose a get_amino_acids_percent() method returning
    fractions, while newer releases (this project was built against
    1.88) expose an amino_acids_percent property returning
    percentages (0-100). This helper normalizes either form so the
    rest of the codebase can rely on one consistent convention.
    """
    if hasattr(analysis, "amino_acids_percent"):
        raw = analysis.amino_acids_percent
        return {aa: pct / 100.0 for aa, pct in raw.items()}
    return analysis.get_amino_acids_percent()

def _aliphatic_index(sequence: str) -> float:
    """
    Aliphatic index (Ikai, 1980): the relative volume of a protein
    occupied by aliphatic side chains (Ala, Val, Ile, Leu). Higher
    values are associated with greater thermostability.

        AI = mol%(Ala) + 2.9 * mol%(Val) + 3.9 * (mol%(Ile) + mol%(Leu))

    where mol%(X) = 100 * (count of X / sequence length). The index has
    no fixed upper bound; values above 100 are possible for sequences
    rich in Val/Ile/Leu.
    """
    n = len(sequence)
    if n == 0:
        return 0.0
    mole_percent = {aa: 100.0 * sequence.count(aa) / n for aa in "AVIL"}
    return (
        mole_percent["A"]
        + 2.9 * mole_percent["V"]
        + 3.9 * (mole_percent["I"] + mole_percent["L"])
    )

def _molecular_formula(sequence: str) -> Tuple[Dict[str, int], str, int]:
    """
    Molecular formula of the whole polypeptide.

    Sums the per-residue atom counts (C, H, N, O, S) from 
    and adds one water molecule (H2, O1) back for the free termini.
    Assumes all cysteines are reduced (disulfide formation would remove
    2 H per bond).

    Returns (atom_counts, formula_string, total_atom_count).
    """
    c = h = n = o = s = 0
    for aa in sequence:
        d_c, d_h, d_n, d_o, d_s = [aa]
        c += d_c
        h += d_h
        n += d_n
        o += d_o
        s += d_s
    h += 2  # free alpha-amino (+H) and alpha-carboxyl (+OH) => +H2O overall
    o += 1
    atom_counts = {"C": c, "H": h, "N": n, "O": o, "S": s}
    formula = "".join(
        f"{element}{atom_counts[element]}"
        for element in ("C", "H", "N", "O", "S")
        if atom_counts[element]
    )
    return atom_counts, formula, sum(atom_counts.values())

def calculate_properties(raw_sequence: str) -> SequenceProperties:
    """
    Compute the standard set of sequence-derived physicochemical
    descriptors for a protein sequence.

    Interpretation notes:
    - GRAVY (Grand Average of Hydropathy): positive = more hydrophobic
      on average, negative = more hydrophilic. A quick first-pass signal
      for membrane association.
    - Instability index: empirical score (Guruprasad et al., 1990).
      Above 40 is classically flagged as "likely unstable in vitro".
    - Aromaticity: relative frequency of Phe/Trp/Tyr -- relevant for
      UV-absorbance-based concentration measurements.
    - Extinction coefficients: estimated at 280 nm assuming Cys residues
      are either all reduced or all oxidized (disulfide-bonded); the
      true value for a folded protein lies between these two bounds.
    - Secondary structure fraction: a residue-propensity-based estimate,
      not a real structural prediction -- treat as a rough signal only.

    Raises
    ------
    MultiRecErr if the input contains more than one FASTA record.
    ValueError if no valid sequence content is provided.
    """
    header_count = count_fasta_headers(raw_sequence)
    if header_count > 1:
        raise MultiRecErr(
            f"Input contains {header_count} FASTA records. This single-sequence "
            "view analyses one chain at a time; concatenating chains would give "
            "a wrong molecular weight and pI. Use batch analysis for multi-record "
            "input."
        )

    sequence, warnings = clean_sequence(raw_sequence)
    if not sequence:
        raise ValueError("No valid sequence provided.")

    analyzable_sequence = "".join(ch for ch in sequence if ch in set_AA)
    if not analyzable_sequence:
        raise ValueError(
            "Sequence contains no standard amino acid letters (A-Y, "
            "excluding B/J/O/U/X/Z) -- nothing left to analyze."
        )

    analysis = ProteinAnalysis(analyzable_sequence)

    instability = analysis.instability_index()
    verdict = "Likely stable" if instability <= 40 else "Likely unstable"

    ext_reduced, ext_oxidized = analysis.molar_extinction_coefficient()
    helix, turn, sheet = analysis.secondary_structure_fraction()

    atom_counts, molecular_formula, total_atoms = _molecular_formula(analyzable_sequence)

    return SequenceProperties(
        length=len(sequence),
        molecular_weight_da=analysis.molecular_weight(),
        isoelectric_point=analysis.isoelectric_point(),
        gravy=analysis.gravy(),
        instability_index=instability,
        instability_verdict=verdict,
        aromaticity=analysis.aromaticity(),
        charge_at_ph7=analysis.charge_at_pH(7.0),
        cys_count=sequence.count("C"),
        extinction_coeff_reduced=ext_reduced,
        extinction_coeff_oxidized=ext_oxidized,
        aliphatic_index=_aliphatic_index(analyzable_sequence),
        molecular_formula=molecular_formula,
        atom_counts=atom_counts,
        total_atoms=total_atoms,
        secondary_structure_fraction={
            "helix": helix,
            "turn": turn,
            "sheet": sheet,
        },
        amino_acid_percent=aa_fracs(analysis),
        warnings=warnings,
    )

@dataclass
class BatchResult:
    """
    Outcome of running calculate_properties() on one FASTA record.

    Exactly one of ``properties`` / ``error`` is set: a record that fails
    (e.g. no standard residues) is reported rather than aborting the
    whole batch.
    """

    record_id: str
    description: str
    properties: Optional[SequenceProperties]
    error: Optional[str]

def calculate_batch(raw_text: str) -> List[BatchResult]:
    """
    Parse ``raw_text`` as (possibly multi-record) FASTA and compute
    properties for every record. Records that raise ValueError are
    captured as BatchResult.error instead of propagating.
    """
    results: List[BatchResult] = []
    for record in parse_fasta(raw_text):
        try:
            props = calculate_properties(record.sequence)
        except ValueError as exc:
            results.append(BatchResult(record.record_id, record.description, None, str(exc)))
        else:
            results.append(BatchResult(record.record_id, record.description, props, None))
    return results
