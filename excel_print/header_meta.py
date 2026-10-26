"""Document metadata in the header (titles, units, currency, reporting dates, notes).

The table header has two parts: a *metadata block* (title, subtitle, "тыс. $", "USD thousand", report
date …) followed by the *column headings*. When a column is not printed, a metadata label that happens
to sit in that column would disappear even though it is needed to read the printed figures.

General rules (no workbook-specific cell addresses):
  * column headings start at the first header row that has text in two or more printed cells;
    every header row above it belongs to the metadata block;
  * a cell of the metadata block in an unprinted column is carried over when it is short display text
    (or a date) — not a bare number, not in a column hidden in the workbook (hidden helper data never
    leaks), and not already visible in a printed cell of the same row;
  * it is written into the nearest free printed cell of the same row (keeping its side of the table,
    font and style); when no free cell exists it is reported, not forced.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

MAX_META_CHARS = 80
NUMBER_ONLY = re.compile(r"^[\s\d.,\-+%()]+$")
DATE_LIKE = re.compile(r"\b\d{1,4}[./-]\d{1,2}[./-]\d{1,4}\b")


@dataclass
class MetaCell:
    row: int
    col: int
    text: str
    hidden_col: bool = False      # column hidden in the original workbook
    merged: bool = False
    merge_cols: tuple[int, int] | None = None   # first/last column of its merged area
    font_size: float = 11.0
    bold: bool = False
    italic: bool = False


@dataclass
class Placement:
    source: tuple[int, int]
    target: tuple[int, int]
    text: str
    align: str                    # "left" / "right" / "keep"


@dataclass
class MetaPlan:
    metadata_rows: list[int]
    placements: list[Placement] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    visible_merged: list[MetaCell] = field(default_factory=list)   # anchored in an unprinted column, shown via its merge


def heading_start(header_rows: list[int], printed_text: dict[tuple[int, int], str], merge_of: dict[tuple[int, int], str],
                  selected: list[int]) -> int | None:
    """First header row with text in two or more distinct printed cells (a merged area counts once)."""
    for r in header_rows:
        areas = {merge_of.get((r, c)) or f"{r},{c}" for c in selected if (printed_text.get((r, c)) or "").strip()}
        if len(areas) >= 2:
            return r
    return None


def plan_metadata(header_rows: list[int], selected: list[int], printed_text: dict[tuple[int, int], str],
                  merge_of: dict[tuple[int, int], str], candidates: list[MetaCell]) -> MetaPlan:
    start = heading_start(header_rows, printed_text, merge_of, selected)
    meta_rows = [r for r in header_rows if start is None or r < start] if start is not None else []
    plan = MetaPlan(meta_rows)
    used: set[tuple[int, int]] = set()
    for cell in sorted(candidates, key=lambda m: (m.row, m.col)):
        text = " ".join((cell.text or "").split())
        if cell.row not in meta_rows or not text or cell.col in selected:
            continue
        where = f"“{text[:40]}” ({cell.row}/{cell.col})"
        if cell.hidden_col:
            plan.skipped.append(f"{where}: column hidden in the workbook — not printed")
            continue
        if len(text) > MAX_META_CHARS:
            plan.skipped.append(f"{where}: too long to be a header label — not printed")
            continue
        if NUMBER_ONLY.match(text) and not DATE_LIKE.search(text):
            plan.skipped.append(f"{where}: a bare number — not treated as metadata")
            continue
        if any(" ".join((printed_text.get((cell.row, c)) or "").split()) == text for c in selected):
            continue  # already visible
        if cell.merge_cols and any(cell.merge_cols[0] <= c <= cell.merge_cols[1] for c in selected):
            plan.visible_merged.append(cell)   # e.g. a title merged across the table: shown by its printed part
            continue
        order = sorted(selected, key=lambda c: (abs(c - cell.col), -c))
        target = next((c for c in order if (cell.row, c) not in used and not (printed_text.get((cell.row, c)) or "").strip()
                       and not merge_of.get((cell.row, c))), None)
        if target is None:
            plan.skipped.append(f"{where}: no free printed cell in that row — not printed")
            continue
        used.add((cell.row, target))
        align = "right" if cell.col > target else ("left" if cell.col < target else "keep")
        plan.placements.append(Placement((cell.row, cell.col), (cell.row, target), text, align))
    return plan
