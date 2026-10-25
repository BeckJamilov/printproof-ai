"""Regression test: manual mode must keep matching the expected results in tests/eval_expected.json.

The expected results were written before testing (see output/evaluation.md). This test is free:
it uses the saved case PDFs in tests/eval_pdfs/ and no API calls.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import evaluation  # noqa: E402

CASES = evaluation.load_expected()["cases"]


def test_case_pdfs_exist():
    for case in CASES:
        assert (evaluation.PDF_DIR / case["file"]).exists(), case["file"]


@pytest.fixture(scope="module")
def manual():
    return evaluation.run_manual()


@pytest.mark.parametrize("case_id", [c["id"] for c in CASES])
def test_manual_mode_matches_expected(manual, case_id):
    case = next(c for c in manual["cases"] if c["id"] == case_id)
    wrong = {name: (c["expected"], c["actual"]["status"], c["actual"]["pages"])
             for name, c in case["checks"].items() if not c["pages_match"]}
    assert not wrong, wrong


def test_no_false_positives_or_missed_problems(manual):
    s = manual["summary"]
    assert s["false_positives"] == 0 and s["missed_problems"] == 0


def test_compare_classifies_outcomes():
    assert evaluation.compare({"status": "Pass"}, {"status": "Fail", "pages": [1]})["outcome"] == "false_positive"
    assert evaluation.compare({"status": "Fail", "pages": [1]}, {"status": "Pass", "pages": []})["outcome"] == "missed_problem"
    assert evaluation.compare({"status": "Fail", "pages": [1]},
                              {"status": "Needs Review", "pages": [1]})["outcome"] == "wrong_problem_type"
    wrong_pages = evaluation.compare({"status": "Fail", "pages": [1]}, {"status": "Fail", "pages": [2]})
    assert wrong_pages["outcome"] == "correct" and not wrong_pages["pages_match"]
