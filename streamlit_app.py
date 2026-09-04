"""
streamlit_app.py -- web front-end for the Protein Toolkit.

Reuses core/ (the same calculation code as the desktop GUI) with no
Tkinter or Matplotlib dependency, so it deploys cleanly to Streamlit
Community Cloud.

Run locally:
    streamlit run streamlit_app.py

Deploy:
    push to GitHub, then create an app at https://share.streamlit.io
    pointing at this file. Embed the resulting URL in a page with
    ``?embed=true`` appended.
"""

from __future__ import annotations

import io
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

from core.sequence_props import (
    MultipleRecordsError,
    SequenceProperties,
    calculate_batch,
    calculate_properties,
)
from core.uniprot import UniProtError, fetch_fasta

GITHUB_URL = "https://github.com/<your-username>/protein_toolkit"

_LOGO_PATH = Path(__file__).parent / "assets" / "logo.png"
LOGO = str(_LOGO_PATH) if _LOGO_PATH.exists() else None

st.set_page_config(
    page_title="Protein Toolkit",
    page_icon=LOGO or "🧬",
    layout="wide",
)
if LOGO:
    st.logo(LOGO, size="large")

# Amino-acid classes, used to colour the composition chart.
AA_CLASS = {
    **{aa: "Nonpolar" for aa in "GAVLIPMFW"},
    **{aa: "Polar uncharged" for aa in "STCYNQ"},
    **{aa: "Acidic (−)" for aa in "DE"},
    **{aa: "Basic (+)" for aa in "KRH"},
}
CLASS_COLORS = {
    "Nonpolar": "#4C72B0",
    "Polar uncharged": "#55A868",
    "Acidic (−)": "#C44E52",
    "Basic (+)": "#8172B2",
}


# --------------------------------------------------------------------------
# rendering helpers (pure -- take a SequenceProperties, return a DataFrame)
# --------------------------------------------------------------------------

def properties_table(p: SequenceProperties) -> pd.DataFrame:
    rows = [
        ("Length", f"{p.length} aa"),
        ("Molecular weight", f"{p.molecular_weight_da:,.1f} Da"),
        ("Theoretical pI", f"{p.isoelectric_point:.2f}"),
        ("Net charge at pH 7.0", f"{p.charge_at_ph7:+.2f}"),
        ("Molecular formula", p.molecular_formula),
        ("Total atoms", f"{p.total_atoms:,}"),
        ("GRAVY", f"{p.gravy:.3f}"),
        ("Aliphatic index", f"{p.aliphatic_index:.2f}"),
        ("Instability index", f"{p.instability_index:.2f}  ({p.instability_verdict})"),
        ("Aromaticity", f"{p.aromaticity:.3f}"),
        ("Cysteine count", str(p.cys_count)),
        ("Ext. coeff (reduced)", f"{p.extinction_coeff_reduced:,.0f} M⁻¹cm⁻¹"),
        ("Ext. coeff (oxidized)", f"{p.extinction_coeff_oxidized:,.0f} M⁻¹cm⁻¹"),
    ]
    for name, frac in p.secondary_structure_fraction.items():
        rows.append((f"Secondary structure — {name}", f"{frac * 100:.1f} %"))
    return pd.DataFrame(rows, columns=["Property", "Value"])


def composition_chart(p: SequenceProperties) -> alt.Chart:
    frame = pd.DataFrame(
        {
            "Amino acid": list(p.amino_acid_percent),
            "Percent": [v * 100 for v in p.amino_acid_percent.values()],
        }
    )
    frame["Class"] = frame["Amino acid"].map(AA_CLASS)
    frame = frame.sort_values("Amino acid")
    return (
        alt.Chart(frame)
        .mark_bar()
        .encode(
            x=alt.X("Amino acid:N", sort=list(frame["Amino acid"])),
            y=alt.Y("Percent:Q", title="% of sequence"),
            color=alt.Color(
                "Class:N",
                scale=alt.Scale(
                    domain=list(CLASS_COLORS), range=list(CLASS_COLORS.values())
                ),
                legend=alt.Legend(orient="top", title=None),
            ),
            tooltip=[
                "Amino acid",
                alt.Tooltip("Percent:Q", format=".2f"),
                "Class",
            ],
        )
        .properties(height=340)
    )


def flat_record(p: SequenceProperties) -> dict:
    """One flat dict of every value -- one row of the batch/CSV export."""
    data = {
        "length": p.length,
        "molecular_weight_da": round(p.molecular_weight_da, 2),
        "isoelectric_point": round(p.isoelectric_point, 2),
        "charge_at_ph7": round(p.charge_at_ph7, 2),
        "gravy": round(p.gravy, 3),
        "aliphatic_index": round(p.aliphatic_index, 2),
        "instability_index": round(p.instability_index, 2),
        "instability_verdict": p.instability_verdict,
        "aromaticity": round(p.aromaticity, 4),
        "cys_count": p.cys_count,
        "extinction_coeff_reduced": round(p.extinction_coeff_reduced),
        "extinction_coeff_oxidized": round(p.extinction_coeff_oxidized),
        "molecular_formula": p.molecular_formula,
        "total_atoms": p.total_atoms,
    }
    for element, count in p.atom_counts.items():
        data[f"atoms_{element}"] = count
    for name, frac in p.secondary_structure_fraction.items():
        data[f"ss_{name}_pct"] = round(frac * 100, 2)
    for aa, frac in sorted(p.amino_acid_percent.items()):
        data[f"aa_percent_{aa}"] = round(frac * 100, 2)
    return data


def xlsx_bytes(frame: pd.DataFrame) -> bytes:
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        frame.to_excel(writer, index=False, sheet_name="results")
    return buffer.getvalue()


# --------------------------------------------------------------------------
# UI
# --------------------------------------------------------------------------

if LOGO:
    logo_col, title_col = st.columns([1, 7], vertical_alignment="center")
    logo_col.image(LOGO, width=96)
    title_col.title("Protein Toolkit")
else:
    st.title("🧬 Protein Toolkit")
st.caption(
    f"Sequence-based physicochemical property calculator · [source on GitHub]({GITHUB_URL})"
)

single_tab, batch_tab = st.tabs(["Single sequence", "Batch"])

# ---- single sequence ----
with single_tab:
    fetch_col, spacer = st.columns([1, 2])
    with fetch_col:
        accession = st.text_input("Fetch by UniProt accession", placeholder="P69905")
        if st.button("Fetch from UniProt", use_container_width=True):
            if not accession.strip():
                st.warning("Enter an accession, e.g. P69905.")
            else:
                try:
                    st.session_state["seq_input"] = fetch_fasta(accession.strip())
                    st.toast(f"Fetched {accession.strip()}")
                except UniProtError as exc:
                    st.error(str(exc))

    sequence = st.text_area(
        "Sequence (raw text or a single FASTA record)",
        key="seq_input",
        height=170,
        placeholder="MVLSPADKTNVKAAWGKVGAHAGEYGAEALERMFLSFPTTKTYFPHF…",
    )

    if st.button("Calculate", type="primary"):
        if not sequence or not sequence.strip():
            st.warning("Enter a sequence first.")
        else:
            try:
                props = calculate_properties(sequence)
            except MultipleRecordsError:
                st.warning(
                    "The input holds more than one FASTA record. "
                    "Switch to the **Batch** tab for multi-record input."
                )
            except ValueError as exc:
                st.error(str(exc))
            else:
                for warning in props.warnings:
                    st.warning(warning)

                a, b, c, d = st.columns(4)
                a.metric("Length", f"{props.length} aa")
                b.metric("Mol. weight", f"{props.molecular_weight_da:,.0f} Da")
                c.metric("Theoretical pI", f"{props.isoelectric_point:.2f}")
                d.metric("GRAVY", f"{props.gravy:.3f}")

                left, right = st.columns([1, 1])
                left.dataframe(
                    properties_table(props),
                    hide_index=True,
                    use_container_width=True,
                )
                right.altair_chart(composition_chart(props), use_container_width=True)

                export = pd.DataFrame([flat_record(props)])
                dl1, dl2 = st.columns(2)
                dl1.download_button(
                    "Download CSV",
                    export.to_csv(index=False).encode("utf-8"),
                    "protein_properties.csv",
                    "text/csv",
                    use_container_width=True,
                )
                dl2.download_button(
                    "Download Excel",
                    xlsx_bytes(export),
                    "protein_properties.xlsx",
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    use_container_width=True,
                )

# ---- batch ----
with batch_tab:
    st.write(
        "Paste FASTA with one or more records, and/or upload FASTA files. "
        "Each record is analysed independently; failures are shown in the table."
    )
    uploads = st.file_uploader(
        "FASTA files",
        type=["fasta", "fa", "faa", "txt"],
        accept_multiple_files=True,
    )
    pasted = st.text_area("…or paste FASTA text", height=150, key="batch_text")

    if st.button("Run batch", type="primary"):
        blocks: list[str] = []
        for uploaded in uploads or []:
            raw = uploaded.read().decode("utf-8", errors="replace").strip()
            if raw and not raw.lstrip().startswith(">"):
                stem = uploaded.name.rsplit(".", 1)[0]
                raw = f">{stem}\n{raw}"
            if raw:
                blocks.append(raw)
        if pasted and pasted.strip():
            blocks.append(pasted.strip())
        combined = "\n".join(blocks)

        if not combined.strip():
            st.warning("Upload a file or paste some FASTA text first.")
        else:
            results = calculate_batch(combined)
            if not results:
                st.warning("No FASTA records found in the input.")
            else:
                summary_rows, full_rows = [], []
                for result in results:
                    if result.error:
                        summary_rows.append(
                            {"record_id": result.record_id, "note": result.error}
                        )
                        full_rows.append(
                            {
                                "record_id": result.record_id,
                                "description": result.description,
                                "error": result.error,
                            }
                        )
                        continue
                    p = result.properties
                    summary_rows.append(
                        {
                            "record_id": result.record_id,
                            "length": p.length,
                            "MW (Da)": round(p.molecular_weight_da, 1),
                            "pI": round(p.isoelectric_point, 2),
                            "charge pH7": round(p.charge_at_ph7, 2),
                            "GRAVY": round(p.gravy, 3),
                            "aliphatic": round(p.aliphatic_index, 1),
                            "instability": round(p.instability_index, 1),
                            "formula": p.molecular_formula,
                            "note": "; ".join(p.warnings),
                        }
                    )
                    full_rows.append(
                        {
                            "record_id": result.record_id,
                            "description": result.description,
                            **flat_record(p),
                            "warnings": "; ".join(p.warnings),
                            "error": "",
                        }
                    )

                errors = sum(1 for r in results if r.error)
                st.success(
                    f"{len(results) - errors} record(s) analysed, {errors} error(s)."
                )
                st.dataframe(
                    pd.DataFrame(summary_rows), hide_index=True, use_container_width=True
                )

                full = pd.DataFrame(full_rows)
                dl1, dl2 = st.columns(2)
                dl1.download_button(
                    "Download full results (CSV)",
                    full.to_csv(index=False).encode("utf-8"),
                    "protein_batch.csv",
                    "text/csv",
                    use_container_width=True,
                )
                dl2.download_button(
                    "Download full results (Excel)",
                    xlsx_bytes(full),
                    "protein_batch.xlsx",
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    use_container_width=True,
                )
