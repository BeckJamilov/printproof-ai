"""Automated tests for pdf_checker.py.

Run from the Final Project folder with:
    python -m pytest
"""

import sys
from pathlib import Path

import pymupdf
import pytest

PROJECT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_DIR))

from pdf_checker import (  # noqa: E402
    FAIL,
    NEEDS_REVIEW,
    PASS,
    PDFCheckError,
    Requirements,
    check_pdf,
    check_pdf_file,
    format_pages,
    identify_paper_size,
    render_page_preview,
)

SAMPLES = PROJECT_DIR / "sample_pdfs"
STANDARD = Requirements(max_pages=5, paper_size="US Letter", min_font_size_pt=10, min_margin_in=1.0)


def result(report, name):
    return next(r for r in report.results if r.name == name)


def make_pdf(build) -> bytes:
    """Create a small in-memory PDF for edge-case tests."""
    doc = pymupdf.open()
    build(doc)
    data = doc.tobytes()
    doc.close()
    return data


# --- Sample files ----------------------------------------------------------

def test_good_sample_passes_everything():
    report = check_pdf_file(str(SAMPLES / "good_sample.pdf"), STANDARD)
    assert report.page_count == 3
    assert report.overall_status == PASS
    assert all(r.status == PASS for r in report.results)


def test_bad_sample_fails_overall():
    report = check_pdf_file(str(SAMPLES / "bad_sample.pdf"), STANDARD)
    assert report.overall_status == FAIL


def test_bad_sample_page_count():
    r = result(check_pdf_file(str(SAMPLES / "bad_sample.pdf"), STANDARD), "Page count")
    assert r.status == FAIL
    assert r.actual == "6 pages"
    assert r.problem_pages == [6]


def test_bad_sample_wrong_paper_size_on_page_2():
    r = result(check_pdf_file(str(SAMPLES / "bad_sample.pdf"), STANDARD), "Paper size")
    assert r.status == FAIL
    assert r.problem_pages == [2]
    assert "A4" in r.details[0] and "210 × 297 mm" in r.details[0]


def test_bad_sample_small_fonts_found_with_sizes():
    r = result(check_pdf_file(str(SAMPLES / "bad_sample.pdf"), STANDARD), "Minimum font size")
    assert r.status == FAIL
    assert r.problem_pages == [3, 6]
    assert "7.0 pt" in r.actual
    assert "7, 8 pt" in r.details[0]
    assert r.highlights, "problem text should be located for the page preview"


def test_bad_sample_text_too_close_to_edges():
    r = result(check_pdf_file(str(SAMPLES / "bad_sample.pdf"), STANDARD), "Minimum margins")
    assert r.status == FAIL
    assert r.problem_pages == [4, 6]
    assert "left 0.25 in" in r.details[0]
    assert "bottom" in r.details[1]


def test_bad_sample_passes_when_rules_are_relaxed():
    relaxed = Requirements(max_pages=10, paper_size=None, min_font_size_pt=7, min_margin_in=0.25)
    assert check_pdf_file(str(SAMPLES / "bad_sample.pdf"), relaxed).overall_status == PASS


def test_a4_selection_flags_letter_pages():
    r = result(check_pdf_file(str(SAMPLES / "good_sample.pdf"), Requirements(paper_size="A4")), "Paper size")
    assert r.status == FAIL
    assert r.problem_pages == [1, 2, 3]


def test_skipped_requirements_are_not_reported():
    report = check_pdf_file(str(SAMPLES / "good_sample.pdf"), Requirements(max_pages=3))
    assert [r.name for r in report.results] == ["Page count"]


# --- Needs Review cases (do not guess) ---------------------------------------

def test_scanned_image_pdf_needs_review():
    def build(doc):
        page = doc.new_page(width=612, height=792)
        pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 50, 65), False)
        pix.clear_with(200)
        page.insert_image(page.rect, pixmap=pix)

    report = check_pdf(make_pdf(build), STANDARD)
    assert result(report, "Minimum font size").status == NEEDS_REVIEW
    assert result(report, "Minimum margins").status == NEEDS_REVIEW
    assert report.overall_status == NEEDS_REVIEW


def test_blank_pdf_needs_review():
    report = check_pdf(make_pdf(lambda doc: doc.new_page(width=612, height=792)), STANDARD)
    assert result(report, "Minimum font size").status == NEEDS_REVIEW
    assert result(report, "Minimum margins").status == NEEDS_REVIEW


def test_landscape_letter_needs_review():
    def build(doc):
        page = doc.new_page(width=792, height=612)
        page.insert_text((100, 120), "Landscape chart page", fontsize=12)

    r = result(check_pdf(make_pdf(build), STANDARD), "Paper size")
    assert r.status == NEEDS_REVIEW
    assert r.review_pages == [1]


def test_rotated_page_margins_use_visible_orientation():
    def build(doc):
        page = doc.new_page(width=612, height=792)
        page.insert_text((20, 400), "Close to the left edge before rotation", fontsize=12)
        page.set_rotation(90)

    report = check_pdf(make_pdf(build), Requirements(min_margin_in=1.0))
    margins = report.pages[0].margins_in
    # After a 90° rotation the unrotated left edge becomes the top edge.
    assert margins["top"] < 0.4
    assert result(report, "Minimum margins").status == FAIL


# --- Bad input ---------------------------------------------------------------

def test_non_pdf_bytes_raise_clear_error():
    with pytest.raises(PDFCheckError):
        check_pdf(b"this is not a pdf", STANDARD)


def test_empty_file_raises_clear_error():
    with pytest.raises(PDFCheckError):
        check_pdf(b"", STANDARD)


def test_password_protected_pdf_raises_clear_error():
    doc = pymupdf.open()
    doc.new_page().insert_text((72, 72), "secret", fontsize=12)
    data = doc.tobytes(encryption=pymupdf.PDF_ENCRYPT_AES_256, owner_pw="o", user_pw="u")
    with pytest.raises(PDFCheckError, match="password"):
        check_pdf(data, STANDARD)


# --- Helpers -----------------------------------------------------------------

def test_identify_paper_size():
    assert identify_paper_size(612, 792) == "US Letter"
    assert identify_paper_size(595.28, 841.89) == "A4"
    assert identify_paper_size(792, 612) == "US Letter (landscape)"
    assert identify_paper_size(500, 500) == "Custom"


def test_format_pages():
    assert format_pages([1, 2, 3, 5]) == "pages 1–3, 5"
    assert format_pages([4]) == "page 4"


def test_preview_renders_png():
    data = (SAMPLES / "bad_sample.pdf").read_bytes()
    report = check_pdf(data, STANDARD)
    highlights = [h for r in report.results for h in r.highlights if h.page == 3]
    png = render_page_preview(data, 3, highlights, min_margin_in=1.0)
    assert png.startswith(b"\x89PNG")
