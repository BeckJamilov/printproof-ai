"""Excel Print Optimizer — tests that need no Excel (pure Python).

Column parsing, the conservative row filter, page fitting, PDF verification and failure handling
(with a fake engine). Integration tests with real Excel are in test_excel_integration.py.
"""

import sys
from pathlib import Path

import pymupdf
import pytest

PROJECT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_DIR))

from excel_print.columns import (ColumnInputError, format_columns, index_to_letter, letter_to_index,  # noqa: E402
                                 parse_area, parse_columns)
from excel_print.excel_engine import ExcelEngineError, ExcelUnavailableError  # noqa: E402
from excel_print.layout import (Geometry, font_warnings, paginate, pages_at, plan_page_count,  # noqa: E402
                                plan_readability, text_width_profiles)
from excel_print.model import CellInfo, ColumnInfo, OptimizeSettings, RowInfo, SheetData  # noqa: E402
from excel_print.optimizer import optimize  # noqa: E402
from excel_print.row_filter import decide_rows, is_total_formula  # noqa: E402
from excel_print.verify import ExpectedText, verify_pdf  # noqa: E402

# ---- columns ---------------------------------------------------------------------------------------------

def test_parse_columns_letters_and_ranges():
    sel = parse_columns("D, E, J, BW-BZ")
    assert sel.letters == ["D", "E", "J", "BW", "BX", "BY", "BZ"]
    assert parse_columns("d;e  j, bw:bz").letters == sel.letters
    assert parse_columns("BW–BY").letters == ["BW", "BX", "BY"]  # en dash


def test_parse_columns_reversed_range_and_duplicates():
    sel = parse_columns("BZ-BW, BX, BX")
    assert sel.letters == ["BW", "BX", "BY", "BZ"]
    assert "reversed" in sel.notes[0]
    assert "Listed more than once (used once): BX." in sel.notes


def test_parse_columns_exact_example_normalises_but_never_changes_columns():
    for text in ("D, E, J, BW, BX, BY, BZ", " d,e ,j,  bw ,bx,BY , bz ", "D E J BW BX BY BZ", "D;E;J;BW;BX;BY;BZ"):
        sel = parse_columns(text)
        assert sel.entered_letters == ["D", "E", "J", "BW", "BX", "BY", "BZ"], text
        assert sel.letters == ["D", "E", "J", "BW", "BX", "BY", "BZ"]
    sel = parse_columns("BZ, D, BW")
    assert sel.entered_letters == ["BZ", "D", "BW"] and sel.letters == ["D", "BW", "BZ"]   # typed order kept for display


def test_columns_outside_the_worksheet_are_rejected_with_a_suggestion():
    from excel_print.columns import check_against_sheet
    sel = parse_columns("D, E, J, BDW, DBX, BY, BZ")      # what the unreadable field produced
    errors, outside = check_against_sheet(sel, letter_to_index("KZ"), (4, 78))
    assert len(errors) == 2
    assert "BDW is outside this worksheet's used range (A–KZ)" in errors[0] and "Did you mean BW" in errors[0]
    assert "Did you mean BX" in errors[1]
    assert outside == []
    errors, outside = check_against_sheet(parse_columns("A, D, CA"), letter_to_index("KZ"), (4, 78))
    assert errors == [] and outside == ["A", "CA"]        # real columns, only outside the print area


@pytest.mark.parametrize("bad", ["", "  ", "D1", "ABCD", "XFE", "BW-", "-BZ", "B-C-D", "1, 2"])
def test_parse_columns_rejects_invalid_input(bad):
    with pytest.raises(ColumnInputError):
        parse_columns(bad)


def test_letter_index_roundtrip_and_formatting():
    for letters in ("A", "Z", "AA", "BZ", "KZ", "XFD"):
        assert index_to_letter(letter_to_index(letters)) == letters
    assert format_columns([4, 5, 10, 75, 76, 77, 78]) == "D, E, J, BW–BZ"
    assert parse_area("'Budget'!$D$3:$BZ$1690") == (4, 3, 78, 1690)


# ---- synthetic sheet for the row filter ------------------------------------------------------------------

B, C, D, E, F, G = 2, 3, 4, 5, 6, 7  # B label, C index, D/E filter, F other number, G comments


def cell(value=None, text=None, font=12.0, bold=False, fill=None, formula="", note="", merged=False):
    if text is None:
        text = "" if value is None else (f"{value:,.2f}" if isinstance(value, (int, float)) else str(value))
    return CellInfo(value=value, text=text, formula=formula, font_size=font, bold=bold, fill=fill, note=note,
                    merged=merged, merge_area="$B$1:$G$1" if merged else "")


def make_sheet(rows):
    infos, n = [], 0
    for spec in rows:
        n += 1
        r = RowInfo(n, hidden=spec.get("hidden", False), outline_level=spec.get("level", 2))
        r.cells = {B: spec.get("label", cell(f"Project {n}")), C: spec.get("c", cell(float(n), text=str(n))),
                   D: spec.get("d", cell(0.0)), E: spec.get("e", cell(None)), F: spec.get("f", cell(0.0)),
                   G: spec.get("g", cell(None))}
        infos.append(r)
    cols = {c: ColumnInfo(c, index_to_letter(c), 6.0 if c == C else 20.0, 40.0) for c in (B, C, D, E, F, G)}
    return SheetData("S", (B, 1, G, n), True, [1], infos, cols, [B, C, D, E, F, G])


def decisions_for(rows, **kw):
    sheet = make_sheet([{"label": cell("Header", bold=True)}] + rows)
    return {d.row: d for d in decide_rows(sheet, [D, E], OptimizeSettings(**kw))}


def test_ordinary_rows_with_empty_or_zero_filter_columns_are_excluded():
    d = decisions_for([{}, {"d": cell(150.0)}, {"e": cell(0.2)}] + [{}] * 5)
    assert d[2].category == "filtered" and not d[2].keep
    assert d[3].keep and d[3].category == "values"
    assert d[4].keep and d[4].category == "values"
    assert d[1].category == "header" and d[1].keep


def test_zero_can_be_a_meaningful_value():
    d = decisions_for([{}, {"d": cell(0.0)}] + [{}] * 4, zero_is_empty=False)
    assert d[3].keep  # 0 in D counts as a value when zero is meaningful


SECTION = dict(font=14, bold=True, fill=13082801)


def test_empty_colored_heading_is_not_kept_for_its_formatting():
    # a filled, bold, larger heading with zero/empty indicators and nothing relevant below it
    d = decisions_for([{"label": cell("SECTION A", **SECTION), "level": 1}, {}, {}, {"d": cell(5.0), "level": 1}, {}])
    assert not d[2].keep and d[2].category == "empty-section"
    assert not d[3].keep and not d[4].keep


def test_entire_empty_section_is_removed_but_sections_with_data_stay():
    d = decisions_for([
        {"label": cell("EMPTY SECTION", **SECTION), "level": 1}, {}, {},
        {"label": cell("ACTIVE SECTION", **SECTION), "level": 1, "d": cell(70.0)}, {"d": cell(70.0)}, {},
    ])
    assert [d[r].keep for r in range(2, 8)] == [False, False, False, True, True, False]


def test_heading_without_values_is_kept_only_for_a_relevant_descendant():
    d = decisions_for([
        {"label": cell("SECTION", **SECTION), "level": 1},           # 2: no values itself
        {"label": cell("Sub-group", bold=True), "level": 2},         # 3: no values itself
        {"level": 3}, {"level": 3, "d": cell(12.5)},                  # 4 empty, 5 relevant grandchild
        {"label": cell("OTHER SECTION", **SECTION), "level": 1},     # 6: empty section
        {"level": 2},
    ])
    assert d[5].keep and d[5].category == "values"
    assert d[3].keep and d[3].category == "parent" and d[5].parent == 3
    assert d[2].keep and d[2].category == "parent" and d[3].parent == 2   # no orphaned sub-item
    assert not d[4].keep and not d[6].keep and not d[7].keep


def test_numbered_sub_items_belong_to_their_parent_number():
    d = decisions_for([
        {"c": cell(33.0, text="33"), "label": cell("Objects (heading)", fill=13082801)},
        {"c": cell(34.0, text="34"), "label": cell("Construction")},
        {"c": cell("34.1.", text="34.1."), "label": cell("PC contract", fill=13082801)},
        {"c": cell("34.2.", text="34.2."), "label": cell("Other objects", fill=13082801), "d": cell(9.0)},
        {"c": cell(39.0, text="39"), "label": cell("Insurance", fill=13082801)},
    ])
    assert d[5].keep and d[5].parent == 3          # 34.2. belongs to 34, not to the filled row 33
    assert d[3].keep and d[3].category == "parent"
    assert not d[2].keep and not d[4].keep and not d[6].keep


def test_comment_keeps_row_with_zero_indicators():
    # zero in the filter column, but a comment explains the line
    d = decisions_for([{"d": cell(0.0, text="-"), "g": cell("Licence renewal moved to 2023, see memo.")}] + [{}] * 6)
    assert d[2].keep and d[2].category == "comment"


def test_totals_are_kept_with_values_and_dropped_when_all_zero():
    d = decisions_for([{"d": cell(5.0)}, {"label": cell("Total investments"), "d": cell(5.0)},
                       {"label": cell("Итого по разделу")},
                       {"d": cell(0.0, formula="=SUBTOTAL(9,D2:D3)")}, {}, {}])
    assert d[3].keep and d[3].category == "total"
    assert not d[4].keep and "nothing to total" in d[4].reason
    assert not d[5].keep


def test_formatting_alone_never_keeps_a_row():
    d = decisions_for([{"label": cell("Merged bold row", bold=True, merged=True, fill=255, font=16)}, {}, {}, {}])
    assert not d[2].keep


def test_vertical_sum_over_collapsed_hidden_rows_is_an_ordinary_row():
    visible = {1, 2, 3, 10}
    assert is_total_formula("=SUM(D2:D3)", visible)            # sums printed rows -> total
    assert not is_total_formula("=SUM(D4:D9)", visible)        # sums hidden detail rows -> ordinary line
    assert not is_total_formula("=SUM(BM10:BV10)", visible)    # horizontal row sum -> ordinary
    assert is_total_formula("=AGGREGATE(9,5,D2:D9)", visible)


def test_rows_with_comments_or_notes_are_kept():  # noqa: D103
    d = decisions_for([{"g": cell("Delayed: contractor will finish in Q3, budget moved to next year.")},
                       {"label": cell("Project with a note", note="Check with finance")}] + [{}] * 6)
    assert d[2].keep and d[2].category == "comment"
    assert d[3].keep and d[3].category == "comment"


def test_error_values_are_kept_and_flagged():
    d = decisions_for([{"d": cell(-2146826281, text="#DIV/0!")}] + [{}] * 4)
    assert d[2].keep and d[2].uncertain and "error" in d[2].reason


def test_values_in_other_columns_keep_the_row_by_default_and_are_flagged_otherwise():
    rows = [{"f": cell(500.0)}] + [{}] * 4
    keep = decisions_for(rows)
    assert keep[2].keep and keep[2].uncertain and keep[2].category == "other-values"
    drop = decisions_for(rows, keep_rows_with_other_values=False)
    assert not drop[2].keep and drop[2].uncertain and "F has a value" in drop[2].reason


def test_index_column_is_not_treated_as_a_financial_value():
    d = decisions_for([{}] * 6)
    assert all(not x.keep for r, x in d.items() if r > 1)  # column C (1, 2, 3, …) alone keeps nothing


def test_hidden_rows_are_never_printed_even_with_values():
    d = decisions_for([{"d": cell(999.0), "hidden": True}, {}, {}])
    assert not d[2].keep and d[2].category == "hidden"


def test_empty_rows_are_excluded():
    d = decisions_for([{"label": cell(None), "c": cell(None), "d": cell(None), "f": cell(None)}, {}, {}])
    assert d[2].category == "empty" and not d[2].keep


# ---- layout ------------------------------------------------------------------------------------------------

def geom(n_rows, row_h=20.0, widths=(100, 300, 80, 80), orientation="landscape", header=(30.0,), keep=None):
    return Geometry("test", orientation, {i: w for i, w in enumerate(widths)}, list(header),
                    list(range(10, 10 + n_rows)), [row_h] * n_rows, keep or [False] * n_rows)


def test_paginate_keeps_rows_whole_and_headings_with_next_row():
    assert paginate([10, 10, 10], [False] * 3, 25, 25) == [2]
    assert paginate([10, 10, 10, 10], [False, True, False, False], 25, 25) == [1, 3]  # heading moves down
    assert paginate([10, 50], [False, False], 40, 40) is None                            # row taller than a page


def test_readability_finds_fewest_pages_then_largest_zoom():
    g = geom(200)
    plan = plan_readability([g], base_font=12, min_font=6, paper="A3", margins="normal", repeat_header=True)
    assert plan.feasible and plan.effective_font_pt >= 6
    fewer = pages_at(g, plan.zoom + 1, "A3", "normal", True)
    assert fewer is None or fewer[0] > plan.pages  # a larger zoom would need more pages
    smallest = pages_at(g, 50, "A3", "normal", True)[0]
    assert plan.pages == smallest  # never more pages than needed at the minimum size


def test_readability_uses_more_pages_rather_than_smaller_text():
    g = geom(400)
    plan = plan_readability([g], base_font=12, min_font=10, paper="A3", margins="normal", repeat_header=True)
    assert plan.feasible and plan.pages > 1 and plan.effective_font_pt >= 10


def test_readability_infeasible_when_columns_too_wide_at_minimum():
    g = geom(10, widths=(2000, 2000))
    plan = plan_readability([g], base_font=12, min_font=8, paper="A3", margins="normal", repeat_header=True)
    assert not plan.feasible and "too wide" in plan.explanation[0]


def test_page_count_first_uses_largest_zoom_within_limit():
    g = geom(200)
    plan = plan_page_count([g], base_font=12, max_pages=1, paper="A3", margins="normal", repeat_header=True)
    assert plan.feasible and plan.pages == 1
    assert pages_at(g, plan.zoom + 1, "A3", "normal", True) is None or pages_at(g, plan.zoom + 1, "A3", "normal", True)[0] > 1


def test_page_count_first_explains_when_impossible():
    g = geom(3000)
    plan = plan_page_count([g], base_font=12, max_pages=1, paper="A3", margins="normal", repeat_header=True)
    assert not plan.feasible and "cannot fit on 1 page" in plan.explanation[0]


def test_small_text_warnings():
    assert font_warnings(3.5) and "extremely small" in font_warnings(3.5)[0]
    assert font_warnings(5.0) and not font_warnings(7.0)


def test_text_width_profiles_respect_longest_word():
    profiles = text_width_profiles({1: 140.0, 2: 25.0}, {1: 35.0, 2: 10.0})
    assert profiles[0][1] == {1: 140.0, 2: 25.0}          # widest: every text on one line
    assert {1: 85, 2: 25.0} in [w for _, w in profiles]   # capped at 85 characters
    assert all(w[1] >= 35.0 for _, w in profiles)


# ---- verification -------------------------------------------------------------------------------------------

def pdf_with(texts, size=(1190.55, 841.89), font=6.0, pages=1, x=40):
    doc = pymupdf.open()
    for n in range(pages):
        page = doc.new_page(width=size[0], height=size[1])
        y = 50
        for t in texts:   # every page shows the full table width
            page.insert_text((x, y), t, fontsize=font)
            y += font * 1.6
        page.insert_text((560, size[1] - 20), f"Page {n + 1} of {pages}", fontsize=9)
    return doc.tobytes()


def test_verify_passes_for_correct_pdf():
    pdf = pdf_with(["Budget 2026", "1 234,50", "Comment: contractor delayed, see note"])
    exp = [ExpectedText("A1", "Budget 2026", "header"), ExpectedText("B2", "1 234,50", "value"),
           ExpectedText("C2", "Comment: contractor delayed, see note", "comment")]
    checks, stats = verify_pdf(pdf, "A3", "landscape", 1, exp, 6.0)
    assert all(c.passed in (True, None) for c in checks), checks
    assert stats["min_font_pt"] == 6.0  # the 9 pt page footer is not counted


def test_verify_detects_missing_text_small_font_wrong_paper_and_overflow():
    pdf = pdf_with(["1 234,50", "#####"], size=(842, 1191), font=4.0)
    exp = [ExpectedText("B2", "1 234,50", "value"), ExpectedText("C9", "this comment was cut off", "comment")]
    checks, stats = verify_pdf(pdf, "A3", "landscape", 2, exp, 6.0)
    failed = {c.name for c in checks if c.passed is False}
    assert any("Paper is A3" in f for f in failed)
    assert any("Page count" in f for f in failed)
    assert any("≥ 6 pt" in f for f in failed)
    assert any("###" in f for f in failed)
    assert any("nothing clipped" in f for f in failed) and stats["missing"] == ["C9"]


def test_verify_handles_a_broken_pdf():
    checks, _ = verify_pdf(b"not a pdf", "A3", "landscape", 1, [], 6.0)
    assert checks[0].passed is False


# ---- optimizer failure handling (fake engine, no Excel) ------------------------------------------------------

class FakeEngine:
    """Behaves like ExcelSession for a tiny sheet; can be told to fail."""

    def __init__(self, source, fail_export=False, wrong_size=False, fit_zoom=None, row_h=20.0):
        """fit_zoom: the real 'Excel' fits on one page only up to this zoom (and prints 12 pt text
        at 12 x zoom / 100 pt); row_h: row height the model sees."""
        self.fail_export, self.wrong_size = fail_export, wrong_size
        self.fit_zoom, self.row_h, self.zoom, self.exports = fit_zoom, row_h, 100, []
        self.tmpdir = Path(source).parent

    def __enter__(self):
        return self

    def __exit__(self, *a):
        pass

    def read_sheet(self, sheet, selected, extend, read_extra=()):
        self.read_extra = list(read_extra)
        s = make_sheet([{"label": cell("Header")}, {"d": cell(10.0)}, {"d": cell(20.0)}])
        s.selected = selected
        s.columns = {c: ColumnInfo(c, index_to_letter(c), 10, 60) for c in selected}
        for r in s.rows:
            r.cells = {c: r.cells.get(c, cell(None)) for c in list(selected) + list(read_extra)}
        return s

    def prepare(self, sheet, kept):
        pass

    def measure(self, sheet, name, orientation, kept_body, keep_next, widths, numeric, header):
        return Geometry(name, orientation, {c: 60.0 for c in sheet.selected}, [20.0], kept_body,
                        [self.row_h] * len(kept_body), keep_next, widths)

    def overflow_cells(self, rows, cols):
        return []

    def col_widths(self, cols):
        return {c: 60.0 for c in cols}

    def row_heights(self, rows):
        return [self.row_h] * len(rows)

    def page_setup(self, sheet, paper, orientation, margins, zoom, *a, **k):
        self.zoom = zoom

    def write_values(self, col, values):
        pass

    def apply_metadata(self, plan):
        self.meta = plan

    def close_borders(self, sheet, kept_body, header):
        return 0

    def export_pdf(self, out):
        if self.fail_export:
            raise ExcelEngineError("Excel could not export the PDF: simulated failure")
        size = (842, 1191) if self.wrong_size else (1190.55, 841.89)
        self.exports.append(self.zoom)
        if self.fit_zoom is None:
            return pdf_with(["Header", "Project 2", "10.00", "Project 3", "20.00"], size=size, font=7.0)
        pages = 1 if self.zoom <= self.fit_zoom else 2
        return pdf_with(["Header", "Project 2", "10.00", "Project 3", "20.00"], size=size,
                        font=12 * self.zoom / 100, pages=pages)

    def grow_rows(self, rows):
        pass


SETTINGS = OptimizeSettings(columns_text="B, D, E", filter_columns_text="D, E")


def test_failed_pdf_conversion_is_reported_not_hidden(tmp_path):
    res = optimize(tmp_path / "x.xlsx", "S", SETTINGS, engine_factory=lambda p: FakeEngine(p, fail_export=True))
    assert not res.success and res.pdf_bytes is None and "simulated failure" in res.message


def test_pdf_that_fails_verification_is_not_called_successful(tmp_path):
    res = optimize(tmp_path / "x.xlsx", "S", SETTINGS, engine_factory=lambda p: FakeEngine(p, wrong_size=True))
    assert not res.success and res.pdf_bytes  # a draft exists, but it is clearly not verified
    assert any(c.passed is False and "Paper" in c.name for c in res.checks)
    assert len(res.attempts) >= 1


def test_good_fake_run_succeeds(tmp_path):
    res = optimize(tmp_path / "x.xlsx", "S", SETTINGS, engine_factory=lambda p: FakeEngine(p))
    assert res.success, (res.message, [(c.name, c.detail) for c in res.checks])
    assert res.summary["pages"] == 1


def test_missing_excel_gives_a_clear_message(tmp_path):
    def no_excel(path):
        raise ExcelUnavailableError("Microsoft Excel is not installed.")
    res = optimize(tmp_path / "x.xlsx", "S", SETTINGS, engine_factory=no_excel)
    assert not res.success and "rendering engine is not available" in res.message


def test_filter_columns_do_not_have_to_be_printed(tmp_path):
    engines = []

    def factory(p):
        engines.append(FakeEngine(p))
        return engines[-1]
    res = optimize(tmp_path / "x.xlsx", "S", OptimizeSettings(columns_text="B, E", filter_columns_text="D, E"),
                   engine_factory=factory)
    assert res.success, res.message
    assert engines[0].read_extra == [D]                  # D was read from the sheet for filtering only
    assert res.summary["columns"] == "B, E"              # ...and not printed
    kept = {d.row for d in res.decisions if d.keep and d.category == "values"}
    assert kept == {2, 3}                                 # rows with values in the unprinted column D are kept


def test_unprinted_filter_column_still_drives_the_row_filter():
    sheet = make_sheet([{"label": cell("Header")}, {"d": cell(25.0)}, {}, {}, {}])
    sheet.selected = [B, C, G]                            # D and E are read but not printed
    d = {x.row: x for x in decide_rows(sheet, [D, E], OptimizeSettings())}
    assert d[2].keep and d[2].category == "values" and "D" in d[2].reason
    assert not d[3].keep


@pytest.mark.parametrize("cols, filt, msg", [
    ("B, D, 1", "D", "not an Excel column"),
    ("B, D", "BX, 7", "not an Excel column"),
])
def test_invalid_settings_are_rejected_before_excel_starts(tmp_path, cols, filt, msg):
    def must_not_start(path):
        raise AssertionError("Excel should not be started for invalid input")
    res = optimize(tmp_path / "x.xlsx", "S", OptimizeSettings(columns_text=cols, filter_columns_text=filt),
                   engine_factory=must_not_start)
    assert not res.success and msg in res.message
