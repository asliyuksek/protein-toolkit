"""
gui/app.py

Tkinter desktop GUI for the Protein Toolkit -- Tier 1: sequence-based
property calculator.

Structure-based modules (interface descriptors, binding-pocket
characterization) are meant to be added later as additional tabs.
See README.md for the roadmap. The calculation logic deliberately
lives in core/sequence_props.py, not here, so it can be reused by a
future CLI or web frontend without touching this file.
"""

import csv
import os
import sys
import tkinter as tk
from datetime import datetime
from tkinter import filedialog, messagebox, ttk
from tkinter import font as tkfont
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import matplotlib

matplotlib.use("TkAgg")
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure
from matplotlib.patches import Patch

try:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font

    _HAVE_OPENPYXL = True
except ImportError:  # pragma: no cover - openpyxl is a listed dependency
    _HAVE_OPENPYXL = False


def _save_filetypes() -> list:
    types = []
    if _HAVE_OPENPYXL:
        types.append(("Excel workbook", "*.xlsx"))
    types.append(("CSV file", "*.csv"))
    return types


def _default_extension() -> str:
    return ".xlsx" if _HAVE_OPENPYXL else ".csv"


def _write_table(path: str, headers: list, rows: list) -> None:
    """Write ``headers`` + ``rows`` to ``path``.

    An ``.xlsx`` file (when openpyxl is installed) gets every cell
    centre-aligned, a bold frozen header row, and roughly auto-sized
    columns, so it opens looking tidy. A ``.csv`` is a plain fallback:
    a CSV file cannot carry alignment or number formatting -- the
    spreadsheet program decides how each cell is drawn.
    """
    wants_xlsx = path.lower().endswith(".xlsx")
    if wants_xlsx and not _HAVE_OPENPYXL:
        path = path[:-5] + ".csv"
        wants_xlsx = False

    if not wants_xlsx:
        with open(path, "w", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(headers)
            writer.writerows(rows)
        return

    workbook = Workbook()
    sheet = workbook.active
    sheet.append(list(headers))
    for row in rows:
        sheet.append(list(row))

    centre = Alignment(horizontal="center", vertical="center")
    for cell in sheet[1]:
        cell.font = Font(bold=True)
        cell.alignment = centre
    for row in sheet.iter_rows(min_row=2):
        for cell in row:
            cell.alignment = centre

    for column_cells in sheet.columns:
        longest = max(
            (len(str(cell.value)) for cell in column_cells if cell.value is not None),
            default=8,
        )
        letter = column_cells[0].column_letter
        sheet.column_dimensions[letter].width = min(max(longest + 2, 9), 46)

    sheet.freeze_panes = "A2"
    workbook.save(path)

from core.sequence_props import (
    STANDARD_AA,
    MultipleRecordsError,
    SequenceProperties,
    calculate_batch,
    calculate_properties,
    clean_sequence,
)
from core.uniprot import UniProtError, fetch_fasta

APP_TITLE = "Protein Toolkit"
APP_SUBTITLE = "Sequence-based physicochemical property calculator · v0.1"

# ---------- palette ----------
BG = "#f4f5f7"
CARD = "#ffffff"
BORDER = "#d0d7de"
SECTION_BG = "#eef1f5"
STATUS_BG = "#e9ebee"
ACCENT = "#2f6feb"
ACCENT_DARK = "#1f5fd0"
TEXT = "#1f2328"
MUTED = "#57606a"
WARN_BG = "#fff8c5"
WARN_FG = "#5c4400"
WARN_BORDER = "#e6d98a"

# ---------- amino acid classes (for the composition chart) ----------
AA_CLASS = {
    **{aa: "nonpolar" for aa in "GAVLIPMFW"},
    **{aa: "polar" for aa in "STCYNQ"},
    **{aa: "acidic" for aa in "DE"},
    **{aa: "basic" for aa in "KRH"},
}
CLASS_COLOR = {
    "nonpolar": "#4C72B0",
    "polar": "#55A868",
    "acidic": "#C44E52",
    "basic": "#8172B2",
}
CLASS_LABEL = {
    "nonpolar": "Nonpolar",
    "polar": "Polar uncharged",
    "acidic": "Acidic (−)",
    "basic": "Basic (+)",
}


def _bind_clipboard(widget: tk.Misc) -> None:
    """Make Cmd/Ctrl + C/V/X/A work in an Entry or Text widget.

    Tk only binds these to Control on X11/Windows by default, and some
    macOS Tk builds don't wire up Command at all -- so pasting into the
    UniProt accession field silently does nothing. Binding both modifiers
    (and the shifted keysyms) fixes it everywhere.
    """

    def emit(event_name: str):
        def handler(event: "tk.Event") -> str:
            event.widget.event_generate(event_name)
            return "break"

        return handler

    for key, event_name in (("c", "<<Copy>>"), ("v", "<<Paste>>"), ("x", "<<Cut>>")):
        for combo in (f"<Command-{key}>", f"<Control-{key}>",
                      f"<Command-{key.upper()}>", f"<Control-{key.upper()}>"):
            widget.bind(combo, emit(event_name))

    def select_all(event: "tk.Event") -> str:
        target = event.widget
        try:
            if isinstance(target, tk.Text):
                target.tag_add("sel", "1.0", "end-1c")
            else:
                target.select_range(0, "end")
                target.icursor("end")
        except tk.TclError:
            pass
        return "break"

    for combo in ("<Command-a>", "<Control-a>", "<Command-A>", "<Control-A>"):
        widget.bind(combo, select_all)


def _attach_entry_context_menu(entry: tk.Misc) -> None:
    """Right-click Cut/Copy/Paste menu for an Entry (there is none by default)."""
    menu = tk.Menu(entry, tearoff=0)
    menu.add_command(label="Cut", command=lambda: entry.event_generate("<<Cut>>"))
    menu.add_command(label="Copy", command=lambda: entry.event_generate("<<Copy>>"))
    menu.add_command(label="Paste", command=lambda: entry.event_generate("<<Paste>>"))
    menu.add_separator()
    menu.add_command(
        label="Select all",
        command=lambda: (entry.select_range(0, "end"), entry.icursor("end")),
    )

    def popup(event: "tk.Event") -> None:
        menu.tk_popup(event.x_root, event.y_root)

    for sequence in ("<Button-2>", "<Button-3>"):
        entry.bind(sequence, popup)


def _enable_text_undo(widget: tk.Text) -> None:
    """Turn on undo history for a Text widget and bind the usual keys.

    tk.Text ships with an undo *stack* but it is off by default, and on
    Linux/Windows the Ctrl+Z / Ctrl+Y keys are not bound to it. macOS Tk
    binds Cmd+Z already; binding both here is harmless and keeps
    behaviour identical across platforms.
    """
    widget.configure(undo=True, autoseparators=True, maxundo=-1)

    def undo(_event: object) -> str:
        try:
            widget.edit_undo()
        except tk.TclError:
            pass
        return "break"

    def redo(_event: object) -> str:
        try:
            widget.edit_redo()
        except tk.TclError:
            pass
        return "break"

    for sequence in ("<Control-z>", "<Command-z>"):
        widget.bind(sequence, undo)
    for sequence in ("<Control-y>", "<Control-Shift-Z>", "<Command-Shift-Z>", "<Command-y>"):
        widget.bind(sequence, redo)


class ProteinToolkitApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("1040x720")
        self.minsize(900, 640)
        self.configure(bg=BG)

        self.current_result: Optional[SequenceProperties] = None
        self._results_plaintext: str = ""
        self._results_rows: list = []

        self._init_fonts()
        self._init_style()
        self._build_menu()
        self._build_layout()

        self.bind("<Control-Return>", lambda _e: self.calculate())
        self.bind("<Command-Return>", lambda _e: self.calculate())

    # ---------- theming ----------

    def _init_fonts(self) -> None:
        self.font_ui = tkfont.nametofont("TkDefaultFont").copy()
        self.font_ui.configure(size=11)
        self.font_ui_bold = self.font_ui.copy()
        self.font_ui_bold.configure(weight="bold")
        self.font_small = self.font_ui.copy()
        self.font_small.configure(size=10)
        self.font_small_bold = self.font_small.copy()
        self.font_small_bold.configure(weight="bold")
        self.font_title = self.font_ui.copy()
        self.font_title.configure(size=17, weight="bold")
        self.font_mono = tkfont.nametofont("TkFixedFont").copy()
        self.font_mono.configure(size=11)

    def _init_style(self) -> None:
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        style.configure(".", background=BG, foreground=TEXT, font=self.font_ui)
        style.configure("TFrame", background=BG)
        style.configure("TLabel", background=BG, foreground=TEXT)
        style.configure("Header.TLabel", background=BG, foreground=TEXT, font=self.font_title)
        style.configure("Sub.TLabel", background=BG, foreground=MUTED, font=self.font_small)
        style.configure("Status.TLabel", background=STATUS_BG, foreground=MUTED, font=self.font_small)

        style.configure(
            "TLabelframe",
            background=BG,
            bordercolor=BORDER,
            relief="solid",
            borderwidth=1,
        )
        style.configure(
            "TLabelframe.Label",
            background=BG,
            foreground=MUTED,
            font=self.font_small_bold,
        )

        style.configure("TButton", padding=(12, 7), font=self.font_ui, borderwidth=1)
        style.map(
            "TButton",
            background=[("active", "#e9edf2"), ("pressed", "#dfe4ea")],
        )
        style.configure(
            "Accent.TButton",
            padding=(12, 7),
            font=self.font_ui_bold,
            foreground="#ffffff",
            background=ACCENT,
            bordercolor=ACCENT,
        )
        style.map(
            "Accent.TButton",
            background=[("active", ACCENT_DARK), ("pressed", ACCENT_DARK)],
            foreground=[("disabled", "#e6e6e6")],
        )

        style.configure(
            "Treeview",
            background=CARD,
            fieldbackground=CARD,
            foreground=TEXT,
            rowheight=25,
            borderwidth=0,
            font=self.font_ui,
        )
        # Visible selection highlight (the batch table uses it; the main
        # results tree is selectmode="none" so it never shows there).
        style.map(
            "Treeview",
            background=[("selected", ACCENT)],
            foreground=[("selected", "#ffffff")],
        )

    # ---------- UI construction ----------

    def _build_menu(self) -> None:
        menubar = tk.Menu(self)

        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label="Load FASTA...", command=self.load_fasta)
        file_menu.add_command(label="Batch analysis...", command=self._open_batch)
        file_menu.add_separator()
        file_menu.add_command(label="Copy Results", command=self.copy_results)
        file_menu.add_command(label="Export Results...", command=self.export_csv)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.destroy)
        menubar.add_cascade(label="File", menu=file_menu)

        help_menu = tk.Menu(menubar, tearoff=0)
        help_menu.add_command(label="About", command=self.show_about)
        menubar.add_cascade(label="Help", menu=help_menu)

        self.config(menu=menubar)

    def _build_layout(self) -> None:
        outer = ttk.Frame(self, padding=(16, 14))
        outer.pack(fill="both", expand=True)
        outer.columnconfigure(0, weight=1)
        outer.columnconfigure(1, weight=1)
        outer.rowconfigure(2, weight=1)

        # --- header ---
        header = ttk.Frame(outer)
        header.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 12))
        ttk.Label(header, text=APP_TITLE, style="Header.TLabel").pack(anchor="w")
        ttk.Label(header, text=APP_SUBTITLE, style="Sub.TLabel").pack(anchor="w", pady=(2, 0))

        # --- input panel ---
        input_frame = ttk.LabelFrame(
            outer, text="  Sequence input — paste raw or FASTA  ", padding=12
        )
        input_frame.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(0, 12))
        input_frame.columnconfigure(0, weight=1)

        self.seq_text = tk.Text(
            input_frame,
            height=6,
            wrap="char",
            font=self.font_mono,
            bg=CARD,
            fg=TEXT,
            insertbackground=TEXT,
            relief="flat",
            padx=10,
            pady=8,
            highlightthickness=1,
            highlightbackground=BORDER,
            highlightcolor=ACCENT,
        )
        self.seq_text.grid(row=0, column=0, sticky="ew")
        self.seq_text.bind("<KeyRelease>", self._update_counter)
        _enable_text_undo(self.seq_text)
        _bind_clipboard(self.seq_text)

        btn_frame = ttk.Frame(input_frame)
        btn_frame.grid(row=0, column=1, sticky="ns", padx=(12, 0))
        ttk.Button(btn_frame, text="Load FASTA…", command=self.load_fasta).pack(fill="x", pady=(0, 6))
        ttk.Button(btn_frame, text="Calculate", style="Accent.TButton", command=self.calculate).pack(fill="x", pady=(0, 6))
        ttk.Button(btn_frame, text="Clear", command=self.clear_input).pack(fill="x", pady=(0, 6))
        ttk.Button(btn_frame, text="Batch…", command=self._open_batch).pack(fill="x")

        fetch_frame = ttk.Frame(input_frame)
        fetch_frame.grid(row=1, column=0, sticky="ew", pady=(8, 0))
        ttk.Label(fetch_frame, text="UniProt accession", style="Sub.TLabel").pack(side="left")
        self.acc_var = tk.StringVar()
        acc_entry = ttk.Entry(fetch_frame, textvariable=self.acc_var, width=16)
        acc_entry.pack(side="left", padx=(8, 6))
        acc_entry.bind("<Return>", lambda _e: self.fetch_uniprot())
        _bind_clipboard(acc_entry)
        _attach_entry_context_menu(acc_entry)
        ttk.Button(fetch_frame, text="Fetch", command=self.fetch_uniprot).pack(side="left")

        self.count_var = tk.StringVar(value="0 residues")
        ttk.Label(input_frame, textvariable=self.count_var, style="Sub.TLabel").grid(
            row=2, column=0, sticky="w", pady=(6, 0)
        )

        # --- results panel (left: table, right: chart) ---
        results_frame = ttk.LabelFrame(outer, text="  Results  ", padding=(12, 10))
        results_frame.grid(row=2, column=0, sticky="nsew", padx=(0, 6))
        results_frame.rowconfigure(0, weight=1)
        results_frame.columnconfigure(0, weight=1)

        self.results_tree = ttk.Treeview(
            results_frame, columns=("value",), show="tree", selectmode="none"
        )
        self.results_tree.column("#0", width=210, minwidth=170, anchor="w", stretch=False)
        self.results_tree.column("value", width=180, minwidth=120, anchor="w", stretch=True)
        self.results_tree.tag_configure("section", background=SECTION_BG, font=self.font_small_bold)
        self.results_tree.tag_configure("data", font=self.font_ui)
        self.results_tree.grid(row=0, column=0, sticky="nsew")

        tree_scroll = ttk.Scrollbar(results_frame, orient="vertical", command=self.results_tree.yview)
        tree_scroll.grid(row=0, column=1, sticky="ns")
        self.results_tree.configure(yscrollcommand=tree_scroll.set)

        res_actions = ttk.Frame(results_frame)
        res_actions.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(10, 0))
        ttk.Button(res_actions, text="Copy", command=self.copy_results).pack(side="left")
        ttk.Button(res_actions, text="Export…", command=self.export_csv).pack(side="left", padx=(6, 0))

        chart_frame = ttk.LabelFrame(outer, text="  Amino acid composition  ", padding=(12, 10))
        chart_frame.grid(row=2, column=1, sticky="nsew", padx=(6, 0))
        chart_frame.rowconfigure(0, weight=1)
        chart_frame.columnconfigure(0, weight=1)

        self.figure = Figure(figsize=(5, 4), dpi=100)
        self.figure.set_facecolor(CARD)
        self.ax = self.figure.add_subplot(111)
        self.canvas = FigureCanvasTkAgg(self.figure, master=chart_frame)
        self.canvas.get_tk_widget().configure(bg=CARD, highlightthickness=0)
        self.canvas.get_tk_widget().grid(row=0, column=0, sticky="nsew")
        self._draw_placeholder()

        # --- warnings strip ---
        self.warn_text = tk.Text(
            outer,
            height=4,
            wrap="word",
            font=self.font_small,
            bg=WARN_BG,
            fg=WARN_FG,
            relief="flat",
            padx=12,
            pady=9,
            borderwidth=0,
            highlightthickness=1,
            highlightbackground=WARN_BORDER,
            highlightcolor=WARN_BORDER,
            state="disabled",
        )
        self.warn_text.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(12, 0))
        self.warn_text.grid_remove()

        # --- status bar ---
        self.status_var = tk.StringVar(value="Ready.")
        status_bar = ttk.Label(
            outer, textvariable=self.status_var, style="Status.TLabel", anchor="w", padding=(10, 5)
        )
        status_bar.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(12, 0))

    # ---------- actions ----------

    def load_fasta(self) -> None:
        path = filedialog.askopenfilename(
            title="Select a FASTA file",
            filetypes=[("FASTA files", "*.fasta *.fa *.txt"), ("All files", "*.*")],
        )
        if not path:
            return
        with open(path, "r") as f:
            content = f.read()
        self.seq_text.delete("1.0", "end")
        self.seq_text.insert("1.0", content)
        self._update_counter()
        self.status_var.set(f"Loaded: {os.path.basename(path)}")

    def fetch_uniprot(self) -> None:
        accession = self.acc_var.get().strip()
        if not accession:
            messagebox.showinfo("UniProt", "Enter a UniProt accession, e.g. P69905.")
            return
        self.status_var.set(f"Fetching {accession} from UniProt…")
        self.config(cursor="watch")
        self.update_idletasks()
        try:
            fasta = fetch_fasta(accession)
        except UniProtError as exc:
            messagebox.showerror("UniProt fetch failed", str(exc))
            self.status_var.set("UniProt fetch failed.")
            return
        finally:
            self.config(cursor="")
        self.seq_text.delete("1.0", "end")
        self.seq_text.insert("1.0", fasta)
        self._update_counter()
        self.calculate()

    def _open_batch(self, initial_text: Optional[str] = None) -> None:
        existing = getattr(self, "_batch_win", None)
        if existing is not None and existing.winfo_exists():
            existing.deiconify()
            existing.lift()
            existing.focus_set()
            if initial_text:
                existing.set_input(initial_text)
            return

        # Hide the main window while the batch window is up, and bring it
        # back when the batch window closes -- one window at a time.
        self.withdraw()
        try:
            self._batch_win = BatchWindow(self, on_close=self._on_batch_closed)
        except Exception:
            self.deiconify()
            raise
        if initial_text:
            self._batch_win.set_input(initial_text)

    def _on_batch_closed(self) -> None:
        self._batch_win = None
        self.deiconify()
        self.lift()
        self.focus_set()

    def clear_input(self) -> None:
        self.seq_text.delete("1.0", "end")
        self._clear_results()
        self.count_var.set("0 residues")
        self.status_var.set("Cleared.")

    def _clear_results(self) -> None:
        for item in self.results_tree.get_children():
            self.results_tree.delete(item)
        self._results_plaintext = ""
        self._results_rows = []
        self._render_warnings([])
        self._draw_placeholder()
        self.current_result = None

    def calculate(self) -> None:
        raw = self.seq_text.get("1.0", "end")
        try:
            result = calculate_properties(raw)
        except MultipleRecordsError as e:
            self.status_var.set("Multiple FASTA records — use batch analysis.")
            if messagebox.askyesno(
                "Multiple sequences",
                f"{e}\n\nOpen batch analysis with this input now?",
            ):
                self._open_batch(initial_text=raw)
            return
        except ValueError as e:
            messagebox.showerror("Invalid sequence", str(e))
            self.status_var.set("Error: invalid sequence.")
            return
        except Exception as e:  # noqa: BLE001 - surface any unexpected error to the user
            messagebox.showerror("Calculation error", f"Unexpected error: {e}")
            self.status_var.set("Error during calculation.")
            return

        self.current_result = result
        self._render_results(result)
        self._render_chart(result)
        self._render_warnings(result.warnings)

        if result.warnings:
            self.status_var.set("Done, with warnings (see amber panel below).")
        else:
            self.status_var.set(f"Done — {result.length} residues analysed.")

    def _update_counter(self, _event=None) -> None:
        try:
            seq, _ = clean_sequence(self.seq_text.get("1.0", "end"))
        except Exception:  # noqa: BLE001 - never let the counter break typing
            return
        non_std = sum(1 for ch in seq if ch not in STANDARD_AA)
        if non_std:
            self.count_var.set(f"{len(seq)} residues · {non_std} non-standard")
        else:
            self.count_var.set(f"{len(seq)} residues")

    def _render_results(self, r: SequenceProperties) -> None:
        for item in self.results_tree.get_children():
            self.results_tree.delete(item)

        gravy_note = "hydrophobic-leaning" if r.gravy > 0 else "hydrophilic-leaning"
        sections = [
            (
                "Basic properties",
                [
                    ("Length", f"{r.length} aa"),
                    ("Molecular weight", f"{r.molecular_weight_da:,.1f} Da"),
                    ("Theoretical pI", f"{r.isoelectric_point:.2f}"),
                    ("Net charge at pH 7.0", f"{r.charge_at_ph7:+.2f}"),
                ],
            ),
            (
                "Atomic composition",
                [
                    ("Molecular formula", r.molecular_formula),
                    ("Total atoms", f"{r.total_atoms:,}"),
                ]
                + [(f"Atoms {el}", str(r.atom_counts[el])) for el in ("C", "H", "N", "O", "S")],
            ),
            (
                "Hydrophobicity & stability",
                [
                    ("GRAVY", f"{r.gravy:.3f}  ({gravy_note})"),
                    ("Aliphatic index", f"{r.aliphatic_index:.2f}"),
                    ("Instability index", f"{r.instability_index:.2f}  ({r.instability_verdict})"),
                    ("Aromaticity", f"{r.aromaticity:.3f}"),
                ],
            ),
            (
                "UV absorbance / quantification",
                [
                    ("Cysteine count", f"{r.cys_count}"),
                    ("Ext. coeff (reduced)", f"{r.extinction_coeff_reduced:,.0f} M⁻¹cm⁻¹"),
                    ("Ext. coeff (oxidized)", f"{r.extinction_coeff_oxidized:,.0f} M⁻¹cm⁻¹"),
                ],
            ),
            (
                "Estimated secondary structure",
                [
                    (name.capitalize(), f"{frac * 100:.1f} %")
                    for name, frac in r.secondary_structure_fraction.items()
                ],
            ),
            (
                "Amino acid composition (%)",
                [
                    (aa, f"{r.amino_acid_percent.get(aa, 0.0) * 100:.2f}")
                    for aa in _AA_ORDER
                ],
            ),
        ]

        self._results_rows = []
        plain_lines = []
        for title, rows in sections:
            self.results_tree.insert("", "end", text=title, values=("",), tags=("section",))
            plain_lines.append(f"[{title}]")
            for name, value in rows:
                self.results_tree.insert("", "end", text=f"   {name}", values=(value,), tags=("data",))
                self._results_rows.append((name, value))
                plain_lines.append(f"{name}: {value}")
            plain_lines.append("")

        self._results_plaintext = "\n".join(plain_lines).strip()

    def _render_chart(self, r: SequenceProperties) -> None:
        self.ax.clear()
        self.ax.set_facecolor(CARD)

        aas = sorted(r.amino_acid_percent.keys())
        values = [r.amino_acid_percent[aa] * 100 for aa in aas]
        colors = [CLASS_COLOR[AA_CLASS[aa]] for aa in aas]
        self.ax.bar(aas, values, color=colors, width=0.72)

        self.ax.set_ylabel("% of sequence", fontsize=9, color=MUTED)
        self.ax.tick_params(labelsize=8, length=0, colors=MUTED)
        self.ax.set_axisbelow(True)
        self.ax.grid(axis="y", color="#eaecef", linewidth=0.7)
        for side in ("top", "right"):
            self.ax.spines[side].set_visible(False)
        for side in ("left", "bottom"):
            self.ax.spines[side].set_color(BORDER)

        handles = [
            Patch(facecolor=CLASS_COLOR[k], label=CLASS_LABEL[k])
            for k in ("nonpolar", "polar", "acidic", "basic")
        ]
        self.ax.legend(
            handles=handles,
            fontsize=7.5,
            frameon=False,
            ncol=2,
            loc="upper center",
            bbox_to_anchor=(0.5, 1.16),
            handlelength=1.1,
            columnspacing=1.2,
        )
        self.figure.subplots_adjust(top=0.82, bottom=0.1, left=0.12, right=0.97)
        self.canvas.draw()

    def _draw_placeholder(self) -> None:
        self.ax.clear()
        self.ax.set_facecolor(CARD)
        self.ax.text(
            0.5,
            0.5,
            "Run a calculation to see\namino acid composition",
            ha="center",
            va="center",
            fontsize=10,
            color="#8c959f",
            transform=self.ax.transAxes,
        )
        self.ax.set_xticks([])
        self.ax.set_yticks([])
        for spine in self.ax.spines.values():
            spine.set_visible(False)
        self.figure.subplots_adjust(top=0.96, bottom=0.06, left=0.08, right=0.97)
        self.canvas.draw()

    def _render_warnings(self, warnings) -> None:
        self.warn_text.config(state="normal")
        self.warn_text.delete("1.0", "end")
        if warnings:
            self.warn_text.insert("1.0", "\n\n".join(f"⚠  {w}" for w in warnings))
            self.warn_text.grid()
        else:
            self.warn_text.grid_remove()
        self.warn_text.config(state="disabled")

    def copy_results(self) -> None:
        if self.current_result is None or not self._results_plaintext:
            messagebox.showwarning("Nothing to copy", "Run a calculation first.")
            return
        self.clipboard_clear()
        self.clipboard_append(self._results_plaintext)
        self.status_var.set("Results copied to clipboard.")

    def export_csv(self) -> None:
        if self.current_result is None or not self._results_rows:
            messagebox.showwarning("Nothing to export", "Run a calculation first.")
            return
        path = filedialog.asksaveasfilename(
            title="Export results",
            defaultextension=_default_extension(),
            filetypes=_save_filetypes(),
        )
        if not path:
            return

        # Export exactly the rows shown in the Results panel.
        headers = ["property", "value"]
        rows = [["timestamp", datetime.now().isoformat(timespec="seconds")]]
        rows += [[name, value] for name, value in self._results_rows]
        _write_table(path, headers, rows)

        self.status_var.set(f"Exported to {os.path.basename(path)}")

    def show_about(self) -> None:
        messagebox.showinfo(
            "About",
            f"{APP_TITLE}\n{APP_SUBTITLE}\n\n"
            "Tier 1 of a growing protein analysis toolkit.\n"
            "Planned additions: an interface-descriptor module "
            "(homodimer/multimer PDB analysis) and a binding-pocket "
            "characterization module.\n\n"
            "Built with Python, Biopython, Tkinter, and Matplotlib.",
        )


# Amino acids in the order used for the CSV's per-composition columns.
_AA_ORDER = "ACDEFGHIKLMNPQRSTVWY"
_ATOM_ELEMENTS = ("C", "H", "N", "O", "S")
_SS_KEYS = ("helix", "turn", "sheet")

# Canonical column order for a single SequenceProperties, shared by the
# single-sequence export (as rows) and the batch export (as columns).
# Composition values are written as true percentages (8.45, not 0.0845),
# and every float is rounded so the CSV stays tidy.
_PROPERTY_COLUMNS = (
    "length", "molecular_weight_da", "isoelectric_point", "charge_at_ph7",
    "gravy", "aliphatic_index", "instability_index", "instability_verdict",
    "aromaticity", "cys_count", "extinction_coeff_reduced",
    "extinction_coeff_oxidized", "molecular_formula", "total_atoms",
    *(f"atoms_{el}" for el in _ATOM_ELEMENTS),
    *(f"ss_{key}_pct" for key in _SS_KEYS),
    *(f"aa_percent_{aa}" for aa in _AA_ORDER),
)


def _property_values(p: SequenceProperties) -> list:
    """Values matching _PROPERTY_COLUMNS, rounded; composition as percent."""
    values = [
        p.length,
        round(p.molecular_weight_da, 2),
        round(p.isoelectric_point, 2),
        round(p.charge_at_ph7, 2),
        round(p.gravy, 3),
        round(p.aliphatic_index, 2),
        round(p.instability_index, 2),
        p.instability_verdict,
        round(p.aromaticity, 4),
        p.cys_count,
        round(p.extinction_coeff_reduced),
        round(p.extinction_coeff_oxidized),
        p.molecular_formula,
        p.total_atoms,
    ]
    values += [p.atom_counts[el] for el in _ATOM_ELEMENTS]
    values += [round(p.secondary_structure_fraction[key] * 100, 2) for key in _SS_KEYS]
    values += [round(p.amino_acid_percent.get(aa, 0.0) * 100, 2) for aa in _AA_ORDER]
    return values


# The batch table shows the full property set -- the same columns the
# batch export writes -- with an id column first and a note column last.
_BATCH_COLUMNS = ("id", *_PROPERTY_COLUMNS, "note")

_COLUMN_HEADINGS = {
    "id": "ID",
    "note": "Note",
    "length": "Length",
    "molecular_weight_da": "MW (Da)",
    "isoelectric_point": "pI",
    "charge_at_ph7": "Charge pH7",
    "gravy": "GRAVY",
    "aliphatic_index": "Aliphatic",
    "instability_index": "Instability",
    "instability_verdict": "Verdict",
    "aromaticity": "Aromaticity",
    "cys_count": "Cys",
    "extinction_coeff_reduced": "ε reduced",
    "extinction_coeff_oxidized": "ε oxidized",
    "molecular_formula": "Formula",
    "total_atoms": "Atoms",
    "ss_helix_pct": "Helix %",
    "ss_turn_pct": "Turn %",
    "ss_sheet_pct": "Sheet %",
    **{f"atoms_{el}": el for el in _ATOM_ELEMENTS},
}
_LEFT_ALIGNED_COLUMNS = {"id", "molecular_formula", "instability_verdict", "note"}


def _column_heading(key: str) -> str:
    if key in _COLUMN_HEADINGS:
        return _COLUMN_HEADINGS[key]
    if key.startswith("aa_percent_"):
        return f"{key[-1]} %"
    return key


def _column_width(key: str) -> int:
    return {
        "id": 140,
        "note": 220,
        "molecular_formula": 150,
        "instability_verdict": 96,
        "molecular_weight_da": 84,
        "charge_at_ph7": 82,
        "aliphatic_index": 78,
        "instability_index": 82,
        "aromaticity": 88,
        "extinction_coeff_reduced": 84,
        "extinction_coeff_oxidized": 84,
        "total_atoms": 62,
    }.get(key, 58)


class BatchWindow(tk.Toplevel):
    """Analyse a multi-record FASTA and show one row of properties per record."""

    def __init__(self, app: ProteinToolkitApp, on_close=None) -> None:
        super().__init__(app)
        self._app = app
        self._on_close = on_close
        # tree row id -> BatchResult, kept in sync as rows are removed so
        # that Export always matches exactly what is on screen.
        self._row_results: dict = {}

        self.title("Batch analysis — multi-record FASTA")
        self.geometry("940x580")
        self.minsize(760, 460)
        self.configure(bg=BG)
        self.protocol("WM_DELETE_WINDOW", self._close)

        self._build()

    def _close(self) -> None:
        callback = self._on_close
        self.destroy()
        if callback is not None:
            callback()

    def set_input(self, text: str) -> None:
        self.text.delete("1.0", "end")
        self.text.insert("1.0", text.strip() + "\n")
        self.status.set("Input loaded from the main window — press Run.")

    def _build(self) -> None:
        outer = ttk.Frame(self, padding=(14, 12))
        outer.pack(fill="both", expand=True)
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(2, weight=1)

        ttk.Label(
            outer,
            text=(
                "Paste FASTA text, or load one or more FASTA files (they are "
                "appended). Each record is analysed independently; failures "
                "are listed in the Note column instead of stopping the run."
            ),
            style="Sub.TLabel",
            wraplength=880,
        ).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 8))

        self.text = tk.Text(
            outer,
            height=7,
            wrap="char",
            font=self._app.font_mono,
            bg=CARD,
            fg=TEXT,
            insertbackground=TEXT,
            relief="flat",
            padx=10,
            pady=8,
            highlightthickness=1,
            highlightbackground=BORDER,
            highlightcolor=ACCENT,
        )
        self.text.grid(row=1, column=0, sticky="ew")
        _enable_text_undo(self.text)
        _bind_clipboard(self.text)

        actions = ttk.Frame(outer)
        actions.grid(row=1, column=1, sticky="ns", padx=(12, 0))
        ttk.Button(actions, text="Load FASTA files…", command=self._load).pack(fill="x", pady=(0, 6))
        ttk.Button(actions, text="Run", style="Accent.TButton", command=self._run).pack(fill="x", pady=(0, 6))
        ttk.Button(actions, text="Clear", command=self._clear_all).pack(fill="x", pady=(0, 6))
        ttk.Button(actions, text="Remove selected", command=self._remove_selected).pack(fill="x", pady=(0, 6))
        ttk.Button(actions, text="Export…", command=self._export).pack(fill="x", pady=(0, 6))
        ttk.Button(actions, text="Close ↩ back to main", command=self._close).pack(fill="x", pady=(12, 0))

        table = ttk.Frame(outer)
        table.grid(row=2, column=0, columnspan=2, sticky="nsew", pady=(10, 8))
        table.rowconfigure(0, weight=1)
        table.columnconfigure(0, weight=1)

        self.tree = ttk.Treeview(
            table, columns=_BATCH_COLUMNS, show="headings", selectmode="extended"
        )
        for column in _BATCH_COLUMNS:
            self.tree.heading(column, text=_column_heading(column))
            self.tree.column(
                column,
                width=_column_width(column),
                anchor="w" if column in _LEFT_ALIGNED_COLUMNS else "center",
                stretch=column in ("molecular_formula", "note"),
            )
        self.tree.tag_configure("err", foreground="#b3261e")
        self.tree.grid(row=0, column=0, sticky="nsew")
        self.tree.bind("<Delete>", lambda _e: self._remove_selected())
        self.tree.bind("<BackSpace>", lambda _e: self._remove_selected())

        vsb = ttk.Scrollbar(table, orient="vertical", command=self.tree.yview)
        vsb.grid(row=0, column=1, sticky="ns")
        hsb = ttk.Scrollbar(table, orient="horizontal", command=self.tree.xview)
        hsb.grid(row=1, column=0, sticky="ew")
        self.tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)

        self.status = tk.StringVar(value="No records analysed yet.")
        ttk.Label(
            outer,
            textvariable=self.status,
            style="Status.TLabel",
            anchor="w",
            padding=(10, 5),
        ).grid(row=3, column=0, columnspan=2, sticky="ew")

    def _load(self) -> None:
        paths = filedialog.askopenfilenames(
            parent=self,
            title="Select one or more FASTA files",
            filetypes=[("FASTA files", "*.fasta *.fa *.faa *.txt"), ("All files", "*.*")],
        )
        if not paths:
            return

        blocks = []
        for path in paths:
            with open(path, "r") as handle:
                content = handle.read().strip()
            if not content:
                continue
            # A file that is a bare sequence (no ">" header) would collide
            # with every other headerless file on the id "seq1" -- use the
            # file name as the record id in that case.
            if not content.lstrip().startswith(">"):
                stem = os.path.splitext(os.path.basename(path))[0]
                content = f">{stem}\n{content}"
            blocks.append(content)

        if not blocks:
            self.status.set("Selected file(s) were empty.")
            return

        existing = self.text.get("1.0", "end").strip()
        parts = ([existing] if existing else []) + blocks
        self.text.delete("1.0", "end")
        self.text.insert("1.0", "\n".join(parts) + "\n")

        names = ", ".join(os.path.basename(p) for p in paths)
        verb = "Added" if existing else "Loaded"
        self.status.set(f"{verb} {len(paths)} file(s): {names} — press Run.")

    def _clear_table(self) -> None:
        for row in self.tree.get_children():
            self.tree.delete(row)
        self._row_results = {}

    def _clear_all(self) -> None:
        self.text.delete("1.0", "end")
        self._clear_table()
        self.status.set("Cleared.")

    def _remove_selected(self) -> None:
        selected = self.tree.selection()
        if not selected:
            return
        for iid in selected:
            self.tree.delete(iid)
            self._row_results.pop(iid, None)
        remaining = len(self.tree.get_children())
        self.status.set(f"Removed {len(selected)} row(s); {remaining} left in table.")

    def _run(self) -> None:
        results = calculate_batch(self.text.get("1.0", "end"))
        self._clear_table()

        if not results:
            self.status.set("No FASTA records found in the input.")
            return

        errors = 0
        for result in results:
            if result.error:
                errors += 1
                values = (result.record_id, *(["—"] * len(_PROPERTY_COLUMNS)), result.error)
                iid = self.tree.insert("", "end", tags=("err",), values=values)
            else:
                p = result.properties
                note = "; ".join(p.warnings) if p.warnings else ""
                values = (result.record_id, *_property_values(p), note)
                iid = self.tree.insert("", "end", values=values)
            self._row_results[iid] = result

        ok = len(results) - errors
        self.status.set(
            f"{ok} record(s) analysed, {errors} error(s). "
            "Select rows and press Delete to drop them before export."
        )

    def _export(self) -> None:
        rows = self.tree.get_children()
        if not rows:
            messagebox.showwarning("Nothing to export", "Run a batch first.", parent=self)
            return
        path = filedialog.asksaveasfilename(
            parent=self,
            title="Export batch results",
            defaultextension=_default_extension(),
            filetypes=_save_filetypes(),
        )
        if not path:
            return

        # Export exactly the columns and rows shown in the table.
        headers = [_column_heading(column) for column in _BATCH_COLUMNS]
        data = [self.tree.item(iid, "values") for iid in rows]
        _write_table(path, headers, data)

        self.status.set(f"Exported {os.path.basename(path)} ({len(data)} row(s))")


def main() -> None:
    app = ProteinToolkitApp()
    app.mainloop()


if __name__ == "__main__":
    main()
