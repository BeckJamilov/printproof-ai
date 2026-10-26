"""Excel Print Optimizer: read → filter rows → renumber → choose layout → render with Excel → verify.

The geometric model (layout.py) only *ranks* candidate layouts and gives a starting scale. The final
scale is found by exporting real PDFs with Excel and measuring them: a candidate passes only if the
PDF has the allowed number of pages, every value/heading/comment is present, nothing shows ‘###’, the
table keeps a safe distance from the paper edges and (Readability First) the smallest printed text
meets the minimum. The search moves up from the predicted scale until a PDF fails, then bisects, so
the largest scale that really fits is used — not just the first one that fits.
"""

from __future__ import annotations

import math
import re
import time
from collections import Counter
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Callable

from .columns import ColumnInputError, format_columns, index_to_letter, parse_columns
from .excel_engine import ExcelEngineError, ExcelSession, ExcelUnavailableError
from .header_meta import plan_metadata
from .layout import (MARGINS_IN, PAPER_PT, ZOOM_MAX, ZOOM_MIN, Geometry, Plan, balanced_starts, font_warnings,
                     max_width_zoom, pages_at, printable_area,
                     plan_page_count, plan_readability, text_width_profiles, widths_for_cap)
from .model import OptimizationResult, OptimizeSettings, SheetData
from .numbering import renumber
from .row_filter import column_roles, decide_rows
from .verify import ExpectedText, verify_pdf
from .width_search import best_combinations

MAX_EXPORTS_PER_LAYOUT = 10    # real PDF exports in the scale search of one candidate layout
CANDIDATE_LAYOUTS = 4          # best-ranked column-width layouts that get a real-PDF search (pruned when hopeless)
SPARSE_PAGE = 0.45             # a page filled less than this (vs. the fullest page) triggers page balancing
Progress = Callable[[str], None]


@dataclass
class Trial:
    zoom: int
    passed: bool                 # passed every check except the page limit (judged separately)
    pages: int
    min_font: float | None
    note: str
    pdf: bytes | None = None
    checks: list = field(default_factory=list)
    stats: dict = field(default_factory=dict)
    starts: list = field(default_factory=list)   # manual page breaks used (empty = Excel's own pagination)

    def ok(self, limit: int) -> bool:
        return self.passed and 0 < self.pages <= limit


def _natural_widths(sheet: SheetData, kept: set[int], text_cols: list[int]) -> tuple[dict[int, float], dict[int, float]]:
    """Width (Excel characters) that would show each text column's longest entry on one line,
    and the width of its longest single word."""
    natural, minimum = {}, {}
    for c in text_cols:
        longest, word = 0.0, 0.0
        for r in sheet.rows:
            if r.number not in kept or r.number in sheet.header_rows:
                continue
            cell = r.cell(c)
            if not cell.text.strip():
                continue
            scale = cell.font_size / 11 * (1.08 if cell.bold else 1.0)
            for line in cell.text.splitlines():
                longest = max(longest, len(line) * scale)
            word = max(word, max(len(w) for w in cell.text.split()) * scale)
        # never narrower than the longest word of the column's own heading (a column may have no body text)
        head = ExcelSession._header_word_chars(sheet, c, sheet.header_rows)
        minimum[c] = max(word + 2, head)
        natural[c] = max(longest + 2, minimum[c])
    return natural, minimum


def _expected_texts(sheet: SheetData, kept: list[int], roles: dict[int, str], text_of) -> list[ExpectedText]:
    out = []
    header = set(sheet.header_rows)
    for r in kept:
        for c in sheet.selected:
            t = text_of(r, c)
            if not t or not t.strip():
                continue
            kind = "header" if r in header else {"comment": "comment", "label": "label"}.get(roles.get(c, ""), "value")
            out.append(ExpectedText(f"{index_to_letter(c)}{r}", t, kind))
    return out


def _numbering_column(sheet: SheetData, roles: dict[int, str], body_rows) -> int | None:
    """The index column (plain numbers or nested “1.2” text), if its numbers mostly increase down the
    sheet — so it really is a sequence numbering and not an ID code."""
    from .row_filter import numbering_parts
    for c in sheet.selected:
        if roles.get(c) != "index":
            continue
        tops = [numbering_parts(r.cell(c).text)[0][0] for r in body_rows if numbering_parts(r.cell(c).text)]
        # a sequence numbering starts low and grows like a counter (years or ID codes do not)
        if (len(tops) >= 3 and sum(b >= a for a, b in zip(tops, tops[1:])) / (len(tops) - 1) >= 0.8
                and min(tops) <= 3 and max(tops) <= 3 * sum(1 for r in sheet.rows if not r.hidden) + 10):
            return c
    return None


def optimize(source: Path, sheet_name: str, settings: OptimizeSettings, progress: Progress | None = None,
             engine_factory=ExcelSession, workdir: Path | None = None) -> OptimizationResult:
    say = progress or (lambda msg: None)
    started = time.time()
    try:
        selection = parse_columns(settings.columns_text)
        filters = parse_columns(settings.filter_columns_text)
    except ColumnInputError as exc:
        return OptimizationResult(False, None, str(exc))
    # Filter columns may be printed or not: e.g. print D, E, J, BW, BZ but filter on BX and BY.
    filter_only = [c for c in filters.indexes if c not in selection.indexes]
    if settings.mode == "readability" and not 1 <= settings.min_font_pt <= 72:
        return OptimizationResult(False, None, "The minimum font size must be between 1 and 72 pt.")
    if settings.mode == "pages" and not 1 <= settings.max_pages <= 200:
        return OptimizationResult(False, None, "The page limit must be between 1 and 200.")
    if settings.margins not in MARGINS_IN:
        return OptimizationResult(False, None, f"Unknown margin setting “{settings.margins}”.")

    attempts: list[str] = []
    try:
        say("Starting Excel and opening a temporary copy of the workbook…")
        with engine_factory(source) as xl:
            say("Recalculating formulas and reading the selected columns…")
            sheet = xl.read_sheet(sheet_name, selection.indexes, settings.extend_print_area, read_extra=filter_only)
            decisions = decide_rows(sheet, filters.indexes, settings)
            kept = [d.row for d in decisions if d.keep]
            header = [r for r in sheet.header_rows if r in kept]
            kept_body = [r for r in kept if r not in header]
            if not kept_body:
                return OptimizationResult(False, None, "No rows remain after filtering — nothing to print.",
                                          decisions=decisions)
            body_rows = [r for r in sheet.rows if r.number in kept_body]
            roles = column_roles(sheet, body_rows)
            text_cols = [c for c in sheet.selected if roles.get(c) in ("label", "comment")]
            numeric_cols = [c for c in sheet.selected if c not in text_cols]
            by_row = {d.row: d for d in decisions}
            keep_next = [by_row[r].has_printed_children for r in kept_body]
            fonts = [r.cell(c).font_size for r in sheet.rows if r.number in set(kept)
                     for c in sheet.selected if r.cell(c).text.strip()]
            base_font = min(fonts) if fonts else 11.0
            rows_by_number = {r.number: r for r in sheet.rows}

            # Consecutive numbering of the printed rows (temporary copy only)
            new_numbers: dict[int, str] = {}
            num_col = _numbering_column(sheet, roles, body_rows) if settings.renumber else None
            if num_col:
                changes = renumber([(r, rows_by_number[r].cell(num_col).text) for r in kept_body])
                if changes:
                    xl.write_values(num_col, {r: v for r, (_, v) in changes.items()})
                    new_numbers = {r: t for r, (t, _) in changes.items()}
                    for r, t in new_numbers.items():
                        by_row[r].printed_number = t

            def printed_text(r: int, c: int) -> str:
                if c == num_col and r in new_numbers:
                    return new_numbers[r]
                return rows_by_number[r].cell(c).text

            say("Hiding unselected columns and filtered rows (on the copy only)…")
            xl.prepare(sheet, kept)
            # Document metadata (units, titles, dates) from unprinted columns -> free printed header cells
            p_text = {(r.number, c): r.cell(c).text for r in sheet.rows if r.number in header for c in sheet.selected}
            merges = {(r.number, c): r.cell(c).merge_area for r in sheet.rows if r.number in header
                      for c in sheet.selected if r.cell(c).merged}
            meta = plan_metadata(header, sheet.selected, p_text, merges, getattr(sheet, "meta_candidates", []))
            xl.apply_metadata(meta)
            for pl in meta.placements:
                attempts.append(f"Header label “{pl.text}” kept: moved from {index_to_letter(pl.source[1])}{pl.source[0]} "
                                f"(column not printed) to {index_to_letter(pl.target[1])}{pl.target[0]}.")
            fixed = xl.close_borders(sheet, kept_body, header)
            if fixed:
                attempts.append(f"Closed {fixed} cell border(s) that belonged to hidden neighbours or the next row.")
            natural, minimum = _natural_widths(sheet, set(kept), text_cols)
            profiles = text_width_profiles(natural, minimum) if text_cols else [("as is", {})]
            orientations = ["landscape", "portrait"] if settings.orientation == "auto" else [settings.orientation]
            say(f"Measuring {len(profiles)} column-width layout(s) in Excel…")
            measured = [xl.measure(sheet, name, orientations[0], kept_body, keep_next, widths, numeric_cols, header)
                        for name, widths in profiles]
            if text_cols and len(measured) > 1:
                measured += _refine_widths(xl, sheet, measured, natural, minimum, orientations, kept_body, keep_next,
                                           numeric_cols, header, base_font, settings, say)
            geoms = [replace(g, orientation=o) for g in measured for o in orientations]

            plan = _plan(geoms, base_font, settings)
            if not plan.feasible:
                return OptimizationResult(False, None, " ".join(plan.explanation), decisions=decisions,
                                          summary=_summary(sheet, decisions, None, {}, settings, base_font, new_numbers),
                                          limitations=plan.explanation, attempts=attempts)

            # Rank every candidate by the model; search the best few with real PDFs.
            ranked = []
            for g in geoms:
                p = _plan([g], base_font, settings)
                if p.feasible:
                    ranked.append(p)
            ranked.sort(key=lambda p: (p.pages, -p.zoom) if settings.mode == "readability" else (-p.zoom, p.pages))
            for p in ranked:
                attempts.append(f"Model: layout “{p.geometry.name}” ({p.geometry.orientation}) predicts {p.zoom} % "
                                f"on {p.pages} page(s).")
            margins = MARGINS_IN[settings.margins]
            out_dir = Path(workdir) if workdir else Path(xl.tmpdir)
            expected = _expected_texts(sheet, kept, roles, printed_text)
            expected += [ExpectedText(f"{index_to_letter(pl.target[1])}{pl.target[0]}", pl.text, "header") for pl in meta.placements]
            expected += [ExpectedText(f"{index_to_letter(m.col)}{m.row}", m.text, "header") for m in meta.visible_merged]
            best: tuple[Trial, Plan] | None = None
            drafts: list[tuple[Trial, Plan]] = []   # failing PDFs, offered only as an unverified draft
            for cand in ranked[:CANDIDATE_LAYOUTS]:
                g = cand.geometry
                cap = min(ZOOM_MAX, max_width_zoom(g, settings.paper, settings.margins))
                if best is not None and cap <= best[0].zoom and (settings.mode == "pages" or best[0].pages <= cand.pages):
                    attempts.append(f"Skipped layout “{g.name}”: it cannot print larger than {cap} % (best so far {best[0].zoom} %).")
                    continue
                say(f"Applying layout “{g.name}” ({g.orientation}) and searching the largest scale with real PDFs…")
                xl.measure(sheet, g.name, g.orientation, kept_body, keep_next, g.text_widths_chars, numeric_cols, header)
                overflow = xl.overflow_cells(kept, numeric_cols)
                if overflow:
                    for col in {c for c in numeric_cols if any(ref.rstrip("0123456789") == index_to_letter(c) for ref in overflow)}:
                        xl.widen(col)
                    attempts.append(f"Widened column(s) showing ### ({', '.join(overflow[:5])}).")
                g = replace(g, col_widths_pt=xl.col_widths(sheet.selected), body_heights_pt=xl.row_heights(kept_body),
                            header_heights_pt=xl.row_heights(header))
                tried: dict = {}
                applied = g.name
                trial = _search(xl, sheet, g, cand, settings, base_font, header, margins, expected, out_dir, attempts, say,
                                tried)
                drafts += [(t, replace(cand, geometry=g, zoom=t.zoom, pages=t.pages)) for t in tried.values() if t.pdf]
                applied = g.name
                if trial and (best is None or _better(trial, best[0], settings)):
                    best = (trial, replace(cand, geometry=g, zoom=trial.zoom, pages=trial.pages))

            if best is None and not drafts:
                msg = "No layout produced a PDF within the requirements."
                return OptimizationResult(False, None, msg, decisions=decisions,
                                          summary=_summary(sheet, decisions, None, {}, settings, base_font, new_numbers),
                                          attempts=attempts, limitations=[msg])
            if best is None:
                # Nothing passed: offer the draft with the fewest failed checks — clearly marked as not verified.
                best = min(drafts, key=lambda d: (sum(c.passed is False for c in d[0].checks), -d[0].zoom))

            trial, plan = best
            if trial.passed and trial.pages > 1:
                if plan.geometry.name != applied:   # put the chosen layout back into Excel before re-paginating
                    xl.measure(sheet, plan.geometry.name, plan.geometry.orientation, kept_body, keep_next,
                               plan.geometry.text_widths_chars, numeric_cols, header)
                    for col in {c for c in numeric_cols for ref in xl.overflow_cells(kept, numeric_cols)
                                if ref.rstrip("0123456789") == index_to_letter(c)}:
                        xl.widen(col)
                    plan.geometry.body_heights_pt[:] = xl.row_heights(kept_body)
                    plan.geometry.header_heights_pt[:] = xl.row_heights(header)
                trial = _balance(xl, sheet, plan.geometry, trial, settings, header, margins, expected, out_dir, attempts, say)
            # final verification of the delivered PDF, now including the page limit
            checks, stats = verify_pdf(trial.pdf, settings.paper, plan.geometry.orientation, None, expected,
                                       settings.min_font_pt if settings.mode == "readability" else None,
                                       page_limit=settings.max_pages if settings.mode == "pages" else None)
            pdf = trial.pdf
            failed = [c for c in checks if c.passed is False]
            success = bool(pdf) and not failed
            plan.effective_font_pt = base_font * plan.zoom / 100
            plan.explanation = [_explain(trial, plan, settings, attempts)]
            summary = _summary(sheet, decisions, plan, stats, settings, base_font, new_numbers)
            summary["seconds"] = round(time.time() - started, 1)
            measured_font = stats.get("min_font_pt") or plan.effective_font_pt
            warnings = font_warnings(measured_font)
            readability = "extremely small" if measured_font < 4.0 else ("small" if measured_font < 6.0 else "ok")
            summary["readability"] = readability
            if settings.mode == "pages" and readability != "ok":
                warnings.append(f"Fitting everything on {settings.max_pages} page(s) needs {readability} text ({measured_font:.1f} pt). "
                                "Consider allowing more pages or using Readability First.")
            warnings += _decision_warnings(decisions)
            if not success:
                message = ("A PDF was produced but did not pass every check — it is NOT verified. Failed: "
                           + "; ".join(f"{c.name} ({c.detail})" for c in failed) + ".")
            elif readability == "extremely small":
                message = (f"The PDF passed every check, but the printed text is extremely small ({measured_font:.1f} pt) — "
                           "it is not comfortable to read.")
            elif readability == "small":
                message = f"Verified PDF, but the printed text is small ({measured_font:.1f} pt)."
            else:
                message = "Print-ready PDF created and verified."
            limitations = [c.detail for c in checks if c.passed is None] + sheet.notes + meta.skipped
            summary["metadata_carried_over"] = [f"{pl.text} ({index_to_letter(pl.source[1])}{pl.source[0]} → "
                                                f"{index_to_letter(pl.target[1])}{pl.target[0]})" for pl in meta.placements]
            for n in selection.notes + filters.notes:
                warnings.append(n)
            hidden_selected = [index_to_letter(c) for c in sheet.selected if sheet.columns[c].hidden]
            if hidden_selected:
                warnings.append(f"Column(s) {', '.join(hidden_selected)} were hidden in the original workbook and are "
                                "printed because you selected them.")
            widths = {index_to_letter(c): round(w / 72 * 25.4, 1) for c, w in plan.geometry.col_widths_pt.items()}
            return OptimizationResult(success, pdf, message, summary, warnings, limitations, decisions, checks,
                                      attempts, widths)
    except ExcelUnavailableError as exc:
        return OptimizationResult(False, None, f"The spreadsheet rendering engine is not available: {exc} "
                                  "Excel Print Optimizer needs Microsoft Excel on Windows.", attempts=attempts)
    except ExcelEngineError as exc:
        return OptimizationResult(False, None, str(exc), attempts=attempts)
    except Exception as exc:  # e.g. an unexpected COM error from Excel: report it, never claim a result
        return OptimizationResult(False, None, f"Excel reported an unexpected error, so no PDF was produced "
                                  f"({type(exc).__name__}: {exc}).", attempts=attempts)


def _refine_widths(xl, sheet, measured: list[Geometry], natural, minimum, orientations, kept_body, keep_next,
                   numeric_cols, header, base_font: float, s: OptimizeSettings, say: Progress, top: int = 3) -> list[Geometry]:
    """Per-column text widths: a text model scores many description/comment width combinations, and
    the best few are measured in Excel (see width_search.py)."""
    def score(g: Geometry) -> tuple:
        p = _plan([replace(g, orientation=o) for o in orientations], base_font, s)
        if not p.feasible:
            return (-999, 0)
        return (-p.pages, p.zoom) if s.mode == "readability" else (p.zoom, -p.pages)

    text_cols = list(natural)
    found = []
    # The text model can misjudge which width wins, so besides the `top` best proposals also measure up to
    # three that clearly differ (> 25 % in some text column) from every proposal already chosen: the real
    # PDFs decide.
    ranked = best_combinations(measured, sheet, text_cols, natural, minimum, score, top=top + 20)
    chosen = ranked[:top]

    def differs(a: dict, b: dict) -> bool:
        return any(abs(a[c] - b[c]) > 0.25 * max(b[c], 1) for c in text_cols)

    for widths in ranked[top:]:
        if len(chosen) >= top + 3:
            break
        if all(differs(widths, w) for w in chosen):
            chosen.append(widths)
    for widths in chosen:
        name = "widths " + "/".join(f"{index_to_letter(c)} {w:g}" for c, w in widths.items())
        say(f"Measuring a refined layout ({name})…")
        found.append(xl.measure(sheet, name, orientations[0], kept_body, keep_next, widths, numeric_cols, header))
    return found


def _better(a: Trial, b: Trial, s: OptimizeSettings) -> bool:
    """Readability First: fewer pages, then larger text. Page Count First: larger text, then fewer pages.
    Ties: the layout that uses more of the page width (fewer wrapped lines, less empty space at the sides)."""
    fa, fb = round(a.min_font or 0, 2), round(b.min_font or 0, 2)
    wa, wb = a.stats.get("content_width_mm", 0), b.stats.get("content_width_mm", 0)
    if s.mode == "readability":
        return (a.pages, -fa, -wa) < (b.pages, -fb, -wb)
    return (-fa, a.pages, -wa) < (-fb, b.pages, -wb)


def _search(xl, sheet: SheetData, g: Geometry, cand: Plan, s: OptimizeSettings, base_font: float, header: list[int],
            margins, expected: list[ExpectedText], out_dir: Path, log: list[str], say: Progress,
            tried: dict[int, Trial] | None = None) -> Trial | None:
    """Best zoom for the layout currently applied in Excel, judged on real exported PDFs.

    Excel paginates by itself (inherited manual breaks are reset), so the page count follows the real
    row heights and grows steadily with the scale.
    * Readability First: the PDF at the minimum font size gives the fewest pages this layout can reach;
      then the largest scale that keeps exactly that page count is searched.
    * Page Count First: the largest scale whose PDF stays within the page limit.
    Every PDF tried is recorded in `tried` (zoom -> Trial)."""
    tried = {} if tried is None else tried
    exports = 0
    stem = "printproof_" + re.sub(r"[^A-Za-z0-9]+", "_", g.name).strip("_")
    z_cap = min(ZOOM_MAX, max_width_zoom(g, s.paper, s.margins))
    z_floor = ZOOM_MIN
    if s.mode == "readability":
        z_floor = max(ZOOM_MIN, math.ceil(100 * s.min_font_pt / base_font - 1e-9))
    if z_cap < z_floor:
        log.append(f"  {g.name}: columns too wide for the page at {z_floor} % — layout skipped.")
        return None

    def test(z: int, starts: list[int] | None = None) -> Trial:
        nonlocal exports
        key = z if not starts else (z, tuple(starts))
        if key in tried:
            return tried[key]
        xl.page_setup(sheet, s.paper, g.orientation, margins, z, header, starts or [], s.repeat_header)
        exports += 1
        say(f"Checking {z} % with a real PDF…")
        pdf = xl.export_pdf(out_dir / f"{stem}_{z}{'_b' if starts else ''}.pdf")
        checks, stats = verify_pdf(pdf, s.paper, g.orientation, None, expected,
                                   s.min_font_pt if s.mode == "readability" else None)
        missing = stats.get("missing", []) + stats.get("cut_refs", [])
        if missing and exports < MAX_EXPORTS_PER_LAYOUT:
            # text cut off: give those rows more height, then check this scale again
            rows = sorted({int(ref.lstrip("ABCDEFGHIJKLMNOPQRSTUVWXYZ")) for ref in missing})
            xl.grow_rows(rows)
            g.body_heights_pt[:] = xl.row_heights(g.body_rows)
            g.header_heights_pt[:] = xl.row_heights(header)
            log.append(f"  {z} %: text cut off in {', '.join(missing[:4])} — rows made taller, checking again.")
            exports += 1
            xl.page_setup(sheet, s.paper, g.orientation, margins, z, header, starts or [], s.repeat_header)
            pdf = xl.export_pdf(out_dir / f"{stem}_{z}_c.pdf")
            checks, stats = verify_pdf(pdf, s.paper, g.orientation, None, expected,
                                       s.min_font_pt if s.mode == "readability" else None)
        failed = [c.name for c in checks if c.passed is False]
        t = Trial(z, not failed, stats.get("pages", 0), stats.get("min_font_pt"),
                  "passed" if not failed else "failed: " + "; ".join(failed), pdf, checks, stats, list(starts or []))
        tried[key] = t
        log.append(f"  {g.name}, {z} %: {t.pages} page(s), smallest text "
                   f"{t.min_font if t.min_font is not None else '?'} pt — {t.note}.")
        return t

    if s.mode == "readability":
        floor = test(z_floor)
        if not floor.passed:
            log.append(f"  {g.name}: no valid PDF at the minimum size {z_floor} % — layout skipped.")
            return None
        limit = floor.pages
    else:
        limit = s.max_pages

    def ok(z: int) -> bool:
        return test(z).ok(limit)

    z0 = max(z_floor, min(cand.zoom, z_cap))
    lo = z_floor if s.mode == "readability" else None   # largest passing zoom
    hi = None                                            # smallest failing zoom
    if ok(z0):
        lo, step = z0, 2
        while exports < MAX_EXPORTS_PER_LAYOUT:
            z = min(lo + step, z_cap)
            if z <= lo:
                break
            if ok(z):
                lo, step = z, step * 2
            else:
                hi = z
                break
    else:
        hi, step = z0, 2
        while exports < MAX_EXPORTS_PER_LAYOUT and hi > z_floor:
            z = max(hi - step, z_floor if lo is None else lo)
            if lo is not None and z <= lo:
                break
            if ok(z):
                lo = z
                break
            hi = z
            step *= 2
    if lo is None:
        return None
    while hi is not None and hi - lo > 1 and exports < MAX_EXPORTS_PER_LAYOUT:
        mid = (lo + hi) // 2
        if ok(mid):
            lo = mid
        else:
            hi = mid
    best = test(lo)
    if (lo + 1) in tried:
        nxt = tried[lo + 1]
        best.note = (f"largest passing scale; {lo + 1} % was also tested and "
                     + (f"needs {nxt.pages} page(s)" if nxt.passed and nxt.pages > limit else nxt.note))
    elif lo >= z_cap:
        best.note = "largest scale at which the columns still fit the page width"
    return best


def _balance(xl, sheet: SheetData, g: Geometry, trial: Trial, s: OptimizeSettings, header: list[int], margins,
             expected: list[ExpectedText], out_dir: Path, log: list[str], say: Progress) -> Trial:
    """If a page of the chosen PDF is nearly empty (e.g. only the grand total on the last page), spread
    the rows evenly over the same number of pages with manual breaks — kept only if the real PDF has the
    same page count and passes every check."""
    fills = trial.stats.get("page_fill") or []
    if len(fills) < 2 or min(fills) >= SPARSE_PAGE * max(fills):
        return trial
    pw, ph = printable_area(s.paper, g.orientation, s.margins)
    scale = trial.zoom / 100
    head = sum(g.header_heights_pt)
    first = ph / scale - head
    later = ph / scale - (head if s.repeat_header else 0)
    starts_idx = balanced_starts(g.body_heights_pt, g.keep_with_next, first * 0.97, later * 0.97, trial.pages)
    if not starts_idx:
        log.append("  balancing: no even split found — kept Excel's own page breaks.")
        return trial
    starts = [g.body_rows[i] for i in starts_idx]
    say("Spreading the rows evenly over the pages…")
    xl.page_setup(sheet, s.paper, g.orientation, margins, trial.zoom, header, starts, s.repeat_header)
    pdf = xl.export_pdf(out_dir / f"printproof_balanced_{trial.zoom}.pdf")
    checks, stats = verify_pdf(pdf, s.paper, g.orientation, None, expected, s.min_font_pt if s.mode == "readability" else None)
    failed = [c.name for c in checks if c.passed is False]
    if failed or stats.get("pages") != trial.pages:
        log.append(f"  balancing at {trial.zoom} %: {stats.get('pages')} page(s)"
                   + (f", failed: {'; '.join(failed)}" if failed else "") + " — kept Excel's own page breaks.")
        xl.page_setup(sheet, s.paper, g.orientation, margins, trial.zoom, header, [], s.repeat_header)
        return trial
    log.append(f"  balanced page breaks at {trial.zoom} %: {trial.pages} page(s), page fill "
               f"{', '.join(f'{f:.0%}' for f in stats.get('page_fill', []))} (was {', '.join(f'{f:.0%}' for f in fills)}).")
    return Trial(trial.zoom, True, stats["pages"], stats.get("min_font_pt"), trial.note + "; rows spread evenly over the pages",
                 pdf, checks, stats, starts)


def _explain(t: Trial, plan: Plan, s: OptimizeSettings, log: list[str]) -> str:
    g = plan.geometry
    font = f"{t.min_font:.2f} pt" if t.min_font is not None else "unknown"
    tested = sum(1 for a in log if a.startswith("  "))
    if s.mode == "readability":
        head = (f"Fewest pages that keep every text at least {s.min_font_pt:g} pt: {t.pages}. Within that, the largest "
                f"scale that passed every check in a real PDF is {t.zoom} %")
    else:
        head = (f"Largest scale that keeps everything on at most {s.max_pages} page(s), confirmed in a real PDF: "
                f"{t.zoom} % ({t.pages} page(s))")
    return (f"{head}, so the smallest printed text measures {font} (layout “{g.name}”, {g.orientation}; "
            f"{tested} PDF check(s) in total). {t.note[0].upper() + t.note[1:]}.")


def _plan(geoms: list[Geometry], base_font: float, s: OptimizeSettings) -> Plan:
    if s.mode == "readability":
        return plan_readability(geoms, base_font, s.min_font_pt, s.paper, s.margins, s.repeat_header)
    return plan_page_count(geoms, base_font, s.max_pages, s.paper, s.margins, s.repeat_header)


def _summary(sheet: SheetData, decisions, plan: Plan | None, stats: dict, s: OptimizeSettings, base_font: float,
             new_numbers: dict[int, str] | None = None) -> dict:
    cats = Counter(d.category for d in decisions)
    kept = [d for d in decisions if d.keep]
    out = {
        "sheet": sheet.name,
        "print_area": f"{index_to_letter(sheet.print_area[0])}{sheet.print_area[1]}:{index_to_letter(sheet.print_area[2])}{sheet.print_area[3]}",
        "columns": format_columns(sheet.selected),
        "filter_columns": s.filter_columns_text,
        "rows_in_print_area": len(decisions),
        "rows_hidden_in_original": cats["hidden"],
        "rows_printed": len(kept),
        "rows_excluded_by_filter": cats["filtered"] + cats["empty-section"],
        "rows_excluded_empty": cats["empty"],
        "rows_uncertain": sum(d.uncertain for d in decisions),
        "kept_by_reason": {k: v for k, v in cats.items() if k not in ("hidden", "filtered", "empty", "empty-section")},
        "rows_renumbered": len(new_numbers or {}),
        "paper": f"{s.paper}",
        "margins": s.margins,
        "mode": "Readability First" if s.mode == "readability" else "Page Count First",
        "base_font_pt": base_font,
    }
    if plan and plan.feasible:
        out.update({"orientation": plan.geometry.orientation, "zoom_percent": plan.zoom, "pages": stats.get("pages", plan.pages),
                    "planned_effective_font_pt": round(plan.effective_font_pt, 2), "layout": plan.geometry.name,
                    "explanation": plan.explanation})
    if stats.get("min_font_pt") is not None:
        out["measured_min_font_pt"] = stats["min_font_pt"]
        out["measured_typical_font_pt"] = stats["median_font_pt"]
    for k in ("content_width_mm", "content_height_mm", "margin_left_mm", "margin_right_mm", "margin_top_mm",
              "margin_bottom_mm", "page_area_used_percent"):
        if k in stats:
            out[k] = stats[k]
    return out


def _decision_warnings(decisions) -> list[str]:
    out = []
    uncertain = [d for d in decisions if d.uncertain]
    if uncertain:
        out.append(f"{len(uncertain)} row decision(s) need a look — see “Rows that need a look”.")
    return out
