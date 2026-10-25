"""Regression tests for grouped results on long documents (follow-up after Step 6).

A real 32-page PDF produced one line per page for the same problem (e.g. "A4" 32 times). Results are
now grouped for people (`summary`, `groups`) while `details` keeps one line per page. These tests
check that grouping is accurate and never hides a problem page.
"""

import re
import sys
from pathlib import Path

import pymupdf
import pytest

PROJECT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_DIR))

from pdf_checker import MAX_SUMMARY_GROUPS, Requirements, check_pdf, pages_label  # noqa: E402
from report import build_html_report, suggestions_for  # noqa: E402

LETTER, A4, LEGAL = (612, 792), (595.28, 841.89), (612, 1008)
STANDARD = Requirements(max_pages=5, paper_size="US Letter", min_font_size_pt=10, min_margin_in=1.0)
TEXT = "Quarterly results were reviewed and the team agreed on three priorities for next term. "


def make_pdf(pages: list[dict]) -> bytes:
    """Each page: size, left/right/top margins in inches, body font size, optional small_pt note."""
    doc = pymupdf.open()
    for spec in pages:
        w, h = spec.get("size", LETTER)
        left, right, top = (spec.get(k, 1.2) * 72 for k in ("left", "right", "top"))
        page = doc.new_page(width=w, height=h)
        box = pymupdf.Rect(left, top, w - right, h - 2 * 72)
        assert page.insert_textbox(box, TEXT * 4, fontsize=spec.get("font", 11)) >= 0
        if spec.get("small_pt"):
            page.insert_text((left, h - 1.5 * 72), "Source: internal data.", fontsize=spec["small_pt"])
    data = doc.tobytes()
    doc.close()
    return data


def expand(text: str) -> set[int]:
    """'2–4, 7' -> {2, 3, 4, 7}"""
    pages = set()
    for part in text.strip().split(", "):
        lo, _, hi = part.partition("–")
        pages |= set(range(int(lo), int(hi or lo) + 1))
    return pages


def result(report, name):
    return next(r for r in report.results if r.name == name)


def grouped_pages(r) -> set[int]:
    return {n for g in r.groups for n in g.get("pages", [g.get("page")])}


# --- Many pages with the same problem ------------------------------------------

@pytest.fixture(scope="module")
def same_problem_32():
    # Like the real 32-page test: every page A4 with text 0.31 in from the left and right edges.
    data = make_pdf([{"size": A4, "left": 0.31, "right": 0.31} for _ in range(32)])
    return data, check_pdf(data, STANDARD)


def test_identical_paper_problem_is_said_once(same_problem_32):
    _, report = same_problem_32
    paper = result(report, "Paper size")
    assert paper.summary == ["All 32 pages are A4, 8.27 × 11.69 in (210 × 297 mm) — not US Letter."]
    assert len(paper.details) == 32  # every page is still available in the page-by-page details
    assert grouped_pages(paper) == set(range(1, 33))


def test_identical_margins_are_grouped(same_problem_32):
    _, report = same_problem_32
    margins = result(report, "Minimum margins")
    text = " ".join(margins.summary)
    assert "on all 32 pages (32 of 32 pages)" in text
    assert re.search(r"Smallest margin: 0\.3\d in \((left|right) edge, page 1\)", text)
    assert any(line.startswith("All 32 pages: left 0.3") for line in margins.summary)
    assert len(margins.summary) <= 2 + MAX_SUMMARY_GROUPS + 1
    assert len(margins.details) == 32 and grouped_pages(margins) == set(range(1, 33))


def test_fix_suggestions_are_not_repeated_per_page(same_problem_32):
    _, report = same_problem_32
    for r in report.results:
        tips = suggestions_for(r, report.pages)
        assert len(tips) <= MAX_SUMMARY_GROUPS + 3, (r.name, tips)
    paper_tips = suggestions_for(result(report, "Paper size"), report.pages)
    assert paper_tips[0].startswith("Change all 32 pages to US Letter")
    assert not any("A4" in t for t in paper_tips)  # the wrong size is stated once, under "What was found"


def test_html_report_is_short_but_keeps_page_details(same_problem_32):
    data, report = same_problem_32
    html = build_html_report(file_name="long.pdf", pdf_bytes=data, mode="Manual", results=report.results,
                             pages=report.pages, page_count=report.page_count, not_checked=[],
                             min_margin_in=1.0, overall=report.overall_status)
    found = html.split("Issues and how to fix them", 1)[1].split("Flagged pages", 1)[0]
    visible = re.sub(r"<details.*?</details>", "", found, flags=re.S)
    assert visible.count("A4, 8.27") == 1  # stated once in the summary, not 32 times
    assert found.count("<details class='per-page'>") == 2  # paper and margins have per-page details
    assert found.count("Page 32: A4") == 1  # ...and page 32 is still listed there


# --- Different measurements on different pages --------------------------------

def test_different_margins_get_separate_groups_and_nothing_is_hidden():
    specs = ([{"left": 0.4}] * 5 + [{"left": 0.5, "right": 0.6}] * 3 + [{"left": 1.2}] * 2
             + [{"left": round(0.1 + 0.05 * i, 2)} for i in range(6)])  # 6 unique profiles
    report = check_pdf(make_pdf(specs), Requirements(min_margin_in=1.0))
    margins = result(report, "Minimum margins")
    assert grouped_pages(margins) == set(margins.problem_pages)  # no problem page lost
    assert {9, 10}.isdisjoint(margins.problem_pages)  # the two correct pages are not reported
    assert "Pages 1–5 (5 of 16): left 0.40 in." in margins.summary
    # The right margin is measured from the real text (wrapped lines end a bit before the box edge).
    assert any(line.startswith("Pages 6–8 (3 of 16): left 0.50 in, right 0.6") for line in margins.summary)
    more = [line for line in margins.summary if "more page(s) with other measurements" in line]
    assert more, margins.summary  # groups beyond the limit are pointed to, not dropped
    listed = set()
    for line in margins.summary:
        m = re.match(r"(All \d+ pages|Pages? [\d–, ]+)", line)
        if m:
            listed |= set(range(1, 17)) if m.group(1).startswith("All") else expand(m.group(1).split(" ", 1)[1])
    hidden = set(margins.problem_pages) - listed
    in_more_line = expand(re.search(r"\(pages? ([\d–, ]+)\)", more[0]).group(1))
    assert hidden and hidden == in_more_line  # pages not in a summary group are named in the "more" line
    smallest = min(v for g in margins.groups for v in g["sides"].values())
    assert f"Smallest margin: {smallest:.2f} in" in " ".join(margins.summary)


def test_mixed_paper_sizes_are_grouped_by_size():
    specs = [{"size": A4}] * 4 + [{"size": LETTER}] * 3 + [{"size": LEGAL}] * 2
    paper = result(check_pdf(make_pdf(specs), Requirements(paper_size="US Letter")), "Paper size")
    assert paper.summary == [
        "Pages 1–4 (4 of 9) are A4, 8.27 × 11.69 in (210 × 297 mm) — not US Letter.",
        "Pages 8–9 (2 of 9) are US Legal, 8.50 × 14.00 in (216 × 356 mm) — not US Letter.",
    ]
    assert paper.problem_pages == [1, 2, 3, 4, 8, 9]


def test_font_summary_counts_pages_and_shows_few_examples():
    specs = [{"small_pt": 7.8}] * 10 + [{"small_pt": 9}] * 2 + [{}] * 8
    font = result(check_pdf(make_pdf(specs), Requirements(min_font_size_pt=10)), "Minimum font size")
    text = " ".join(font.summary)
    assert "Text smaller than 10 pt on pages 1–12 (12 of 20 pages" in text
    assert "Smallest text: 7.8 pt on page 1." in text
    assert "Sizes below the minimum: 7.8, 9 pt." in text
    examples = font.summary[2]
    assert examples.startswith("Example") and 1 <= examples.count("page ") <= 3  # distinct texts only
    assert len(font.details) == 12 and grouped_pages(font) == set(range(1, 13))
    tips = suggestions_for(font, check_pdf(make_pdf(specs), Requirements(min_font_size_pt=10)).pages)
    assert tips[0] == ("Increase all text to at least 10 pt. Text below the minimum is on pages 1–12 "
                       "(12 of 20); the smallest is 7.8 pt on page 1.")


def test_pages_label():
    assert pages_label(list(range(1, 33)), 32) == "All 32 pages"
    assert pages_label([4], 32) == "Page 4"
    assert pages_label([2, 3, 4, 7], 32) == "Pages 2–4, 7 (4 of 32)"
