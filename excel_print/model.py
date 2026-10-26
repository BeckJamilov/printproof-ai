"""Data read from the workbook (by the Excel engine) and the settings/results of an optimization."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

ERROR_TEXTS = {"#DIV/0!", "#N/A", "#NAME?", "#NULL!", "#NUM!", "#REF!", "#VALUE!", "#SPILL!", "#CALC!",
               "#GETTING_DATA", "#FIELD!", "#BLOCKED!", "#CONNECT!", "#BUSY!", "#UNKNOWN!"}

ValueKind = Literal["empty", "zero", "number", "text", "error"]


@dataclass
class CellInfo:
    value: object = None          # Value2 from Excel after recalculation (number, str, None)
    text: str = ""                # what Excel displays (number format applied)
    formula: str = ""             # "=..." if the cell has a formula
    font_size: float = 11.0
    bold: bool = False
    fill: int | None = None       # RGB as Excel's BGR int, None when the cell has no fill
    wrap: bool = False
    merged: bool = False
    merge_area: str = ""          # e.g. "$D$5:$D$7"
    note: str = ""                # text of an Excel note/comment attached to the cell

    @property
    def kind(self) -> ValueKind:
        if self.text.strip() in ERROR_TEXTS or (isinstance(self.value, int) and self.value < -2_000_000_000):
            return "error"
        v = self.value
        if v is None or (isinstance(v, str) and not v.strip()):
            return "empty"
        if isinstance(v, bool):
            return "number"
        if isinstance(v, (int, float)):
            return "zero" if v == 0 else "number"
        return "text"


@dataclass
class RowInfo:
    number: int
    hidden: bool = False           # hidden in the original workbook (never unhidden)
    outline_level: int = 1         # Excel's OutlineLevel (1 = top level)
    height_pt: float = 15.0
    cells: dict[int, CellInfo] = field(default_factory=dict)  # selected column index -> cell

    def cell(self, col: int) -> CellInfo:
        return self.cells.get(col) or CellInfo()


@dataclass
class ColumnInfo:
    index: int
    letter: str
    width_chars: float
    width_pt: float
    hidden: bool = False           # hidden in the original workbook


@dataclass
class SheetData:
    name: str
    print_area: tuple[int, int, int, int]   # first_col, first_row, last_col, last_row
    print_area_from_workbook: bool
    header_rows: list[int]                  # rows treated as the table header (printed on every page)
    rows: list[RowInfo]                     # every row of the print area (hidden ones included, flagged)
    columns: dict[int, ColumnInfo]          # selected columns
    selected: list[int]
    notes: list[str] = field(default_factory=list)   # facts found while reading (external links etc.)
    meta_candidates: list = field(default_factory=list)   # header text in unprinted columns (possible metadata)

    @property
    def visible_rows(self) -> list[RowInfo]:
        return [r for r in self.rows if not r.hidden]


@dataclass
class OptimizeSettings:
    columns_text: str = "D, E, J, BW, BX, BY, BZ"
    filter_columns_text: str = "BX, BY"
    zero_is_empty: bool = True                 # treat 0 like an empty cell in the filter columns
    keep_rows_with_other_values: bool = True   # conservative: keep rows with values in other selected numeric columns
    paper: Literal["A3", "A4"] = "A3"
    orientation: Literal["landscape", "portrait", "auto"] = "landscape"
    mode: Literal["readability", "pages"] = "readability"
    min_font_pt: float = 6.0                   # Readability First: hard minimum effective printed size
    max_pages: int = 1                         # Page Count First: page limit
    margins: Literal["compact", "narrow", "normal"] = "compact"   # compact = smallest safe margins
    extend_print_area: bool = False            # include selected columns outside the existing print area
    repeat_header: bool = True
    renumber: bool = True                      # consecutive numbers for the printed rows (copy only)


@dataclass
class RowDecision:
    row: int
    keep: bool
    category: str          # header / values / total / comment / other-values / error / parent (kept heading) /
                           # filtered / empty-section / empty / hidden
    reason: str
    uncertain: bool = False
    label: str = ""        # short text from the row to help the user recognise it
    parent: int | None = None            # row number of its heading in the table hierarchy
    has_printed_children: bool = False   # a heading with printed rows below it (keep it with the next row)
    printed_number: str = ""             # new consecutive number, when the row was renumbered


@dataclass
class VerificationCheck:
    name: str
    passed: bool | None    # None = could not be measured
    detail: str


@dataclass
class OptimizationResult:
    success: bool
    pdf_bytes: bytes | None
    message: str
    summary: dict = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)
    decisions: list[RowDecision] = field(default_factory=list)
    checks: list[VerificationCheck] = field(default_factory=list)
    attempts: list[str] = field(default_factory=list)
    column_widths: dict[str, float] = field(default_factory=dict)
