"""Per-column width search for long-text columns (descriptions, comments).

A row is as tall as its most-wrapped cell, so the best widths are found column by column: e.g. a
comment column wide enough for one line, with the description column narrower but still on one line.
Excel's own measurement is slow, so a simple text model scores many combinations first:

  * characters needed by a cell ≈ len(text) × font/11 (× 1.08 if bold) × 1.12 (printing at a reduced
    scale wraps a little earlier than the screen at 100 %), in Excel width units;
  * lines = ceil(needed / (column width − 1));
  * row height = height measured by Excel for the row in the widest layout + extra lines × 1.17 × font.

Only the best few combinations are then measured in Excel (AutoFit) and, after that, checked in real
PDFs — the model only decides what is worth measuring.
"""

from __future__ import annotations

import itertools
import math

from .layout import Geometry, pages_at
from .model import SheetData

LINE_FACTOR = 1.17
PRINT_SLACK = 1.12   # Excel wraps a little earlier when printing at a reduced scale than on screen at 100 %


def _needed_chars(cell) -> float:
    if not cell.text.strip():
        return 0.0
    scale = cell.font_size / 11 * (1.08 if cell.bold else 1.0)
    return max(len(line) for line in cell.text.splitlines()) * scale * PRINT_SLACK


def _lines(need: float, width_chars: float) -> int:
    return max(1, math.ceil(need / max(width_chars - 1.0, 1.0))) if need else 1


def candidate_widths(sheet: SheetData, rows: list[int], col: int, minimum: float, natural: float, limit: int = 8) -> list[float]:
    """Widths at which some printed row of this column needs one line fewer (its 'breakpoints')."""
    by_row = {r.number: r for r in sheet.rows}
    points = {round(natural, 1)}
    for r in rows:
        need = _needed_chars(by_row[r].cell(col))
        for k in (1, 2, 3):
            w = need / k + 1.5
            if minimum <= w <= natural + 0.5:
                points.add(round(w, 1))
    pts = sorted(p for p in points if p >= minimum)
    if len(pts) > limit:   # keep an even spread, always including the narrowest and widest
        idx = sorted({round(i * (len(pts) - 1) / (limit - 1)) for i in range(limit)})
        pts = [pts[i] for i in idx]
    return pts


def estimate(widest: Geometry, sheet: SheetData, widths: dict[int, float], pt_per_char: tuple[float, float]) -> Geometry:
    """Geometry for other text-column widths, from Excel's measurement of the widest layout."""
    by_row = {r.number: r for r in sheet.rows}
    a, b = pt_per_char
    cols = dict(widest.col_widths_pt)
    for c, w in widths.items():
        cols[c] = a * w + b
    heights = []
    for r, h in zip(widest.body_rows, widest.body_heights_pt):
        row = by_row[r]
        extra = 0.0
        for c, w in widths.items():
            cell = row.cell(c)
            need = _needed_chars(cell)
            if not need:
                continue
            more = _lines(need, w) - _lines(need, widest.text_widths_chars.get(c, w))
            extra = max(extra, more * LINE_FACTOR * cell.font_size)
        heights.append(h + extra)
    return Geometry("estimate", widest.orientation, cols, list(widest.header_heights_pt), list(widest.body_rows),
                    heights, list(widest.keep_with_next), dict(widths))


def best_combinations(measured: list[Geometry], sheet: SheetData, text_cols: list[int], natural: dict[int, float],
                      minimum: dict[int, float], score, top: int = 3, max_combos: int = 400) -> list[dict[int, float]]:
    """The `top` text-width combinations with the best model score (score(geometry) -> sortable, higher = better)."""
    if not measured or not text_cols:
        return []
    widest = max(measured, key=lambda g: sum(g.text_widths_chars.values()))
    pairs = [(g.text_widths_chars[c], g.col_widths_pt[c]) for g in measured for c in text_cols if c in g.text_widths_chars]
    xs = [p[0] for p in pairs]
    if len(set(xs)) < 2:
        return []
    mx, my = sum(xs) / len(xs), sum(p[1] for p in pairs) / len(pairs)
    a = sum((x - mx) * (y - my) for x, y in pairs) / sum((x - mx) ** 2 for x in xs)
    b = my - a * mx
    per_col = max(2, int(max_combos ** (1 / len(text_cols))))
    options = [candidate_widths(sheet, widest.body_rows, c, minimum[c], natural[c], per_col) for c in text_cols]
    scored = []
    for combo in itertools.product(*options):
        widths = dict(zip(text_cols, combo))
        scored.append((score(estimate(widest, sheet, widths, (a, b))), widths))
    scored.sort(key=lambda t: t[0], reverse=True)
    out, seen = [], [g.text_widths_chars for g in measured]
    for _, widths in scored:
        if any(all(abs(widths[c] - s.get(c, -99)) < 1.0 for c in text_cols) for s in seen + out):
            continue
        out.append(widths)
        if len(out) == top:
            break
    return out


__all__ = ["best_combinations", "candidate_widths", "estimate", "pages_at"]
