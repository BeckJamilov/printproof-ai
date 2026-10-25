"""Tests for the standalone HTML report (report.py)."""

import re
import sys
from pathlib import Path

import pymupdf

PROJECT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_DIR))

from pdf_checker import Requirements, check_pdf  # noqa: E402
from report import AIDetails, build_html_report, suggestions_for  # noqa: E402

SAMPLES = PROJECT_DIR / "sample_pdfs"
GOOD = (SAMPLES / "good_sample.pdf").read_bytes()
BAD = (SAMPLES / "bad_sample.pdf").read_bytes()
STANDARD = Requirements(max_pages=5, paper_size="US Letter", min_font_size_pt=10, min_margin_in=1.0)


def make(pdf_bytes, reqs=STANDARD, name="doc.pdf", not_checked=(), ai=None):
    report = check_pdf(pdf_bytes, reqs)
    return report, build_html_report(
        file_name=name, pdf_bytes=pdf_bytes, mode="AI" if ai else "Manual", results=report.results,
        pages=report.pages, page_count=report.page_count, not_checked=list(not_checked),
        min_margin_in=reqs.min_margin_in, overall=report.overall_status, ai=ai)


def test_report_is_standalone_html():
    _, html = make(BAD)
    assert html.startswith("<!DOCTYPE html>") and html.rstrip().endswith("</html>")
    # No external files, scripts or web fonts: everything is embedded.
    assert not re.search(r'(src|href)="(https?:|/|\./)', html)
    assert "<script" not in html.lower()
    assert "data:image/png;base64," in html  # page previews are embedded


def test_bad_sample_report_has_measurements_pages_and_fixes():
    _, html = make(BAD, name="bad_sample.pdf")
    for text in ["bad_sample.pdf", "6 pages", "page 6", "Page 2 is A4", "must be US Letter",
                 "Page 3: the smallest text is 7.0 pt", "Increase it to at least 10 pt",
                 "Page 4: move content further from the left edge by 0.75 in", "Shorten the document by at least 1 page"]:
        assert text in html, text


def test_good_sample_report_has_no_invented_problems():
    _, html = make(GOOD, name="good_sample.pdf")
    assert "No problems were found in the checks that were run." in html
    assert "How to fix it" not in html
    assert html.count("b-fail") == 1  # only the CSS rule, no Fail badges


def test_unchecked_requirements_are_not_reported_as_passed():
    reqs = Requirements(max_pages=5)
    _, html = make(GOOD, reqs, not_checked=["Paper size", "Minimum font size", "Minimum margins"])
    assert html.count("Not checked</span>") == 3
    assert "need a manual check" in html
    assert "Paper size</b></td><td><span class='badge b-pass'>" not in html


def test_suggestions_only_for_failed_or_review_checks():
    report = check_pdf(GOOD, STANDARD)
    assert all(suggestions_for(r, report.pages) == [] for r in report.results)


def test_scanned_page_gets_review_advice_not_a_fix():
    doc = pymupdf.open()
    page = doc.new_page(width=612, height=792)
    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 50, 65), False)
    pix.clear_with(200)
    page.insert_image(page.rect, pixmap=pix)
    report = check_pdf(doc.tobytes(), STANDARD)
    font = next(r for r in report.results if r.name == "Minimum font size")
    tips = " ".join(suggestions_for(font, report.pages))
    assert "could not be measured" in tips and "Increase" not in tips


def test_text_from_file_names_and_ai_is_escaped():
    ai = AIDetails(requirements_text="<script>alert(1)</script>", understood=[], clarifications=["<b>x</b>"],
                   summary="<img src=x onerror=alert(1)>", explanations={}, model="gpt-6-luna", run_id="abc")
    _, html = make(BAD, name="<script>evil</script>.pdf", ai=ai)
    assert "<script>evil" not in html and "<script>alert" not in html and "<img src=x" not in html
    assert "&lt;script&gt;evil&lt;/script&gt;.pdf" in html


def test_ai_report_lists_ai_interpretation_and_not_checkable_items():
    ai = AIDetails(
        requirements_text="max 5 pages, double spaced",
        understood=[{"user_wording": "max 5 pages", "interpreted_as": "At most 5 pages", "checkable": True, "note": None},
                    {"user_wording": "double spaced", "interpreted_as": "Double spacing", "checkable": False,
                     "note": "Needs a manual check."}],
        clarifications=["Check double spacing by hand."], summary="Fails the page limit.",
        explanations={"Page count": "The PDF has 6 pages."}, model="gpt-6-luna", run_id="r1",
        usage={"total_tokens": 4000})
    _, html = make(BAD, Requirements(max_pages=5), not_checked=["double spaced"], ai=ai)
    for text in ["AI interpretation", "max 5 pages, double spaced", "Not checkable", "Check double spacing by hand.",
                 "AI explanation:</b> The PDF has 6 pages.", "4,000 tokens", "never the PDF"]:
        assert text in html, text
