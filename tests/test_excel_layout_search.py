"""Excel Print Optimizer — regression tests for the layout search (no Excel needed).

Font maximization under a page limit with real (fake-engine) PDFs, Readability First, consecutive
renumbering, cut-off text and margin checks in the PDF, and the per-column width search.
"""

import sys
from dataclasses import replace
from pathlib import Path

import pymupdf
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from test_excel_print import G, SETTINGS, FakeEngine, cell, make_sheet, pdf_with  # noqa: E402

from excel_print.layout import Geometry  # noqa: E402
from excel_print.numbering import renumber  # noqa: E402
from excel_print.optimizer import optimize  # noqa: E402
from excel_print.verify import ExpectedText, cut_text_lines, verify_pdf  # noqa: E402
from excel_print.width_search import candidate_widths, estimate  # noqa: E402


def settings(**kw):
    return replace(SETTINGS, **kw)


# ---- Page Count First: the largest scale is searched in real PDFs, not taken from the model ------------------

def test_page_count_first_searches_upward_when_the_model_is_too_cautious(tmp_path):
    engines = []

    def factory(p):
        engines.append(FakeEngine(p, fit_zoom=98, row_h=400.0))   # model predicts ~95 %, the real fit is 98 %
        return engines[-1]
    res = optimize(tmp_path / "x.xlsx", "S", settings(mode="pages", max_pages=1), engine_factory=factory)
    assert res.success and res.summary["zoom_percent"] == 98 and res.summary["pages"] == 1
    assert res.summary["measured_min_font_pt"] == pytest.approx(11.76, abs=0.01)   # 12 pt x 98 %
    assert 99 in engines[0].exports             # the next size up was really tried (and needed 2 pages)
    assert len(engines[0].exports) <= 2 * 9     # an efficient search, not every size from 10 % to 120 %


def test_page_count_first_steps_down_when_the_model_is_too_optimistic(tmp_path):
    res = optimize(tmp_path / "x.xlsx", "S", settings(mode="pages", max_pages=1),
                   engine_factory=lambda p: FakeEngine(p, fit_zoom=71, row_h=400.0))
    assert res.success and res.summary["zoom_percent"] == 71 and res.summary["pages"] == 1


def test_page_limit_is_a_hard_constraint(tmp_path):
    res = optimize(tmp_path / "x.xlsx", "S", settings(mode="pages", max_pages=1),
                   engine_factory=lambda p: FakeEngine(p, fit_zoom=5, row_h=400.0))   # never fits on 1 page
    assert not res.success                     # a 2-page PDF is never called a 1-page success
    assert any(c.passed is False and c.name == "At most 1 page(s)" for c in res.checks)


# ---- Readability First --------------------------------------------------------------------------------------

def test_readability_first_maximizes_within_the_fewest_pages(tmp_path):
    res = optimize(tmp_path / "x.xlsx", "S", settings(mode="readability", min_font_pt=10),
                   engine_factory=lambda p: FakeEngine(p, fit_zoom=98, row_h=400.0))
    assert res.success and res.summary["pages"] == 1 and res.summary["zoom_percent"] == 98


def test_readability_first_uses_more_pages_rather_than_smaller_text(tmp_path):
    res = optimize(tmp_path / "x.xlsx", "S", settings(mode="readability", min_font_pt=10),
                   engine_factory=lambda p: FakeEngine(p, fit_zoom=80, row_h=400.0))   # 1 page only below 10 pt
    assert res.success and res.summary["pages"] == 2 and res.summary["measured_min_font_pt"] >= 10


# ---- renumbering -------------------------------------------------------------------------------------------

def test_renumbering_is_consecutive_and_follows_the_hierarchy():
    items = [(10, "1"), (11, "2"), (12, "4"), (13, "5"), (14, "34"), (15, "34.1."), (16, "34.3."), (17, ""),
             (18, "39"), (19, "39.2"), (20, "39.2.1"), (21, "57")]
    changes = renumber(items)
    printed = [changes[r][0] if r in changes else t for r, t in items]
    assert printed == ["1", "2", "3", "4", "5", "5.1.", "5.2.", "", "6", "6.1", "6.1.1", "7"]
    assert changes[12][1] == 3 and changes[15][1] == "5.1."   # whole numbers stay numbers, nested stay text


def test_renumbering_leaves_consecutive_numbers_and_unnumbered_rows_alone():
    assert renumber([(1, "1"), (2, "2"), (3, "2.1."), (4, ""), (5, "Total"), (6, "3")]) == {}


# ---- PDF checks: cut-off text, safe margins, measured layout -------------------------------------------------

def _page_with_lines(text_y, rules):
    doc = pymupdf.open()
    page = doc.new_page(width=1190.55, height=841.89)
    page.insert_text((100, text_y), "Comment text in a cell", fontsize=10)
    for y in rules:
        page.draw_line((90, y), (400, y))
    return pymupdf.open(stream=doc.tobytes(), filetype="pdf")[0]


def test_text_cut_by_a_cell_border_is_detected():
    assert cut_text_lines(_page_with_lines(300, [296.5])) == ["Comment text in a cell"]


def test_borders_above_and_below_text_are_not_a_cut():
    assert cut_text_lines(_page_with_lines(300, [289.0, 303.0])) == []


def test_safe_margin_check_and_layout_measurements():
    exp = [ExpectedText("A1", "Budget", "header")]
    checks, stats = verify_pdf(pdf_with(["Budget"], x=8), "A3", "landscape", None, exp, None, page_limit=1)
    safe = next(c for c in checks if c.name.startswith("Safe margins"))
    assert safe.passed is False and stats["margin_left_mm"] < 5           # 8 pt is about 2.8 mm from the edge
    checks, stats = verify_pdf(pdf_with(["Budget"], x=40), "A3", "landscape", None, exp, None, page_limit=1)
    assert next(c for c in checks if c.name.startswith("Safe margins")).passed is True
    assert stats["margin_left_mm"] == pytest.approx(40 * 25.4 / 72, abs=0.5)
    assert 0 <= stats["page_area_used_percent"] < 5
    assert next(c for c in checks if c.name == "At most 1 page(s)").passed


# ---- per-column width search ---------------------------------------------------------------------------------

def test_width_search_proposes_breakpoints_and_estimates_wrapping():
    long = "Contractor confirmed a delay; the budget moves to next year. " * 2   # about 122 characters
    sheet = make_sheet([{"label": cell("Header")}, {"g": cell(long, font=11)}, {"g": cell("Short note", font=11)}])
    widths = candidate_widths(sheet, [2, 3], G, minimum=12, natural=140)
    assert widths[0] >= 12 and widths[-1] == 140 and len(widths) >= 3
    wide = Geometry("w", "landscape", {2: 100.0, G: 700.0}, [20.0], [2, 3], [15.0, 15.0], [False, False], {G: 140.0})
    narrow = estimate(wide, sheet, {G: 45.0}, (5.0, 5.0))
    assert narrow.col_widths_pt[G] == pytest.approx(230.0)
    assert narrow.body_heights_pt[0] > 15.0 + 2 * 11   # the long comment now needs 3 or more lines
    assert narrow.body_heights_pt[1] == 15.0           # the short one still fits on one line
