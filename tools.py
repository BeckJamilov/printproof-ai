"""Tools the PrintProof agent can call (Step 2).

Each tool runs our existing Step 1 checker (pdf_checker.py) on the uploaded PDF and returns a
small dictionary of measurements. Rules:

- The PDF itself is never sent to the AI. Tools return numbers, statuses and page numbers only.
- Text from inside the PDF is removed from tool outputs, so instructions hidden in a document
  cannot reach the model.
- Inputs from the model are validated; bad values raise ToolInputError so the model can retry.
"""

from __future__ import annotations

import re
import threading
from collections import defaultdict
from typing import Any, Literal

from models import AgentDeps, ToolRecord
from pdf_checker import (
    MM_PER_INCH,
    CheckResult,
    Requirements,
    check_pdf,
    format_pages,
)

MAX_DETAIL_LINES = 10  # keep tool outputs short to save tokens
# The model may ask for several checks at once and PydanticAI runs them in parallel threads.
# PyMuPDF is not thread-safe, so PDF work runs one tool at a time.
_PDF_LOCK = threading.Lock()
MarginUnit = Literal["in", "mm", "cm"]

# Font details look like: Page 3: 4 text run(s) at 7, 8 pt — e.g. "some text". Drop the quote.
_TEXT_SAMPLE = re.compile(r"\s*—\s*e\.g\..*$")


class ToolInputError(ValueError):
    """The model passed a value the tool cannot use."""


def _safe_details(details: list[str]) -> list[str]:
    """Remove document text and cap the number of lines."""
    cleaned = [_TEXT_SAMPLE.sub("", line) for line in details]
    if len(cleaned) > MAX_DETAIL_LINES:
        extra = len(cleaned) - MAX_DETAIL_LINES
        cleaned = cleaned[:MAX_DETAIL_LINES] + [f"...and {extra} more line(s) not shown"]
    return cleaned


def _result_to_output(result: CheckResult) -> dict[str, Any]:
    return {
        "check": result.name,
        "status": result.status,
        "requirement": result.requirement,
        "actual": result.actual,
        "problem_pages": result.problem_pages,
        "review_pages": result.review_pages,
        "details": _safe_details(result.details),
    }


def _run_check(deps: AgentDeps, tool_name: str, arguments: dict[str, Any],
               requirements: Requirements) -> dict[str, Any]:
    with _PDF_LOCK:
        report = check_pdf(deps.pdf_bytes, requirements, file_name=deps.file_name)
    result = report.results[0]
    output = _result_to_output(result)
    deps.tool_records.append(ToolRecord(tool_name, arguments, output, check_result=result))
    return output


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

def get_document_overview(deps: AgentDeps) -> dict[str, Any]:
    """Basic facts about the PDF (no document text): page count, page sizes, text/scan status."""
    with _PDF_LOCK:
        report = check_pdf(deps.pdf_bytes, Requirements(), file_name=deps.file_name)
    by_size: dict[str, list[int]] = defaultdict(list)
    for page in report.pages:
        by_size[page.size_name].append(page.number)
    output = {
        "page_count": report.page_count,
        "page_sizes": {name: format_pages(pages) for name, pages in by_size.items()},
        "pages_with_readable_text": sum(p.has_text for p in report.pages),
        "pages_that_look_scanned": [p.number for p in report.pages if p.looks_scanned],
        "blank_pages": [p.number for p in report.pages if not p.has_text and p.margins_in is None],
    }
    deps.tool_records.append(ToolRecord("get_document_overview", {}, output))
    return output


def check_page_limit(deps: AgentDeps, max_pages: int) -> dict[str, Any]:
    if not isinstance(max_pages, int) or max_pages < 1 or max_pages > 5000:
        raise ToolInputError("max_pages must be a whole number between 1 and 5000.")
    return _run_check(deps, "check_page_limit", {"max_pages": max_pages},
                      Requirements(max_pages=max_pages))


def check_paper_size(deps: AgentDeps, paper_size: Literal["US Letter", "A4"]) -> dict[str, Any]:
    if paper_size not in ("US Letter", "A4"):
        raise ToolInputError("paper_size must be exactly 'US Letter' or 'A4'.")
    return _run_check(deps, "check_paper_size", {"paper_size": paper_size},
                      Requirements(paper_size=paper_size))


def check_min_font_size(deps: AgentDeps, min_font_size_pt: float) -> dict[str, Any]:
    if not 1 <= float(min_font_size_pt) <= 72:
        raise ToolInputError("min_font_size_pt must be between 1 and 72 points.")
    return _run_check(deps, "check_min_font_size", {"min_font_size_pt": float(min_font_size_pt)},
                      Requirements(min_font_size_pt=float(min_font_size_pt)))


def check_min_margins(deps: AgentDeps, min_margin: float, unit: MarginUnit = "in") -> dict[str, Any]:
    """Margins are converted to inches in Python, so the model never does unit math."""
    factors = {"in": 1.0, "mm": 1 / MM_PER_INCH, "cm": 10 / MM_PER_INCH}
    if unit not in factors:
        raise ToolInputError("unit must be 'in', 'mm' or 'cm'.")
    inches = float(min_margin) * factors[unit]
    if not 0 < inches <= 3:
        raise ToolInputError("The margin must be greater than 0 and at most 3 inches (76 mm).")
    return _run_check(deps, "check_min_margins", {"min_margin": float(min_margin), "unit": unit},
                      Requirements(min_margin_in=inches))


CHECK_TOOLS = ("check_page_limit", "check_paper_size", "check_min_font_size", "check_min_margins")
