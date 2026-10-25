# PrintProof AI — Project evidence summary (Step 4)

This file collects the evidence we have for the final report and separates three kinds of
statements:

- **MEASURED** — produced by real runs of the app, tests or API calls; the source file is given.
- **ESTIMATE** — calculated from measured data plus stated assumptions.
- **PENDING** — not done yet; nothing may be claimed until it is.

Last updated 2026-10-25. Repository: https://github.com/BeckJamilov/printproof-ai (Step 6 checks: `output/final_checklist.md`).

## 1. Measured results

### 1.1 Automated tests — MEASURED

`.\.venv\Scripts\python.exe -m pytest` → **69 passed, 4 skipped** (the 4 skipped are the live Portkey
tests, which only run when `RUN_LIVE_AI_TESTS=1`).

| Test file | Tests | Covers |
|---|---|---|
| `tests/test_pdf_checker.py` | 19 | Each check, Needs Review cases (scans, blank, landscape), bad/encrypted files, rotation |
| `tests/test_agent.py` | 22 (4 live) | Tools match the checker, no PDF text in tool outputs, unit conversion, audit trail append-only, validator blocks false reports, Portkey cache logging |
| `tests/test_report.py` | 8 | HTML report is standalone, correct fixes, no invented problems, "Not checked" items, HTML escaping |
| `tests/test_grouping.py` | 8 | Long documents: identical problems said once, different measurements grouped separately, fixes not repeated per page, no problem page hidden (added after the real-world test) |
| `tests/test_evaluation.py` | 16 | The 13 evaluation cases still match the expected results |

The 4 live tests passed when last run with real Portkey calls in Step 2 (runs `95b3e52f4954`,
`46b62071c7fc`, `f4fbaae0c9fb`, `2c0ee4410dda`; the first prompt-injection attempt `d0bfbfabf82f`
was blocked by Azure's content filter and the test was then adjusted).

### 1.2 Accuracy on our own test set — MEASURED (generated files)

Source: `output/evaluation.md`, `output/evaluation_results.json`, expected results in
`tests/eval_expected.json` (recorded 05:19 UTC, before the PDFs were generated at 05:24 UTC).

| Metric | Result |
|---|---|
| Checks with correct status | 52 / 52 |
| Correct status **and** problem pages | 52 / 52 |
| Expected problems found | 14 / 14 |
| False positives / missed problems | 0 / 0 |
| Documents with correct overall verdict | 13 / 13 |
| Check time per document (manual mode) | 0.003–0.044 s |

**How to describe this correctly:** "PrintProof found every problem in 13 test PDFs that we designed
and generated ourselves." It does **not** show accuracy on real documents from Word, Google Docs,
LaTeX or scanners (see §3).

### 1.3 AI mode — MEASURED

Source: `output/audit_trail.json`, `output/evaluation_results.json`.

- 17 AI runs recorded: **10 fresh**, **5 Portkey cache hits**, **2 rejected** before the model ran.
- **Every one of the 21 completed runs reported the same statuses as the Python checker** (15 in Steps 2–3, 6 in Step 6 and the follow-ups); the output
  validator never had to reject a real model's report.
- AI interpretation tested with different wording, e.g. "A4 paper only … 20 mm margins" →
  `check_paper_size("A4")`, `check_min_margins(20, "mm")` (run `e976db5da5cd`); unclear and
  unsupported rules listed instead of guessed (run `f4fbaae0c9fb`).
- Agent tool calls are recorded per run (tool name, arguments, result) in `audit_trail.json`
  (`tool_call` events) and `evaluation_results.json` (`tools_called`).
- HW5 issue confirmed and fixed: tool calls with reasoning on are rejected (run `799d6dcc4858`,
  HTTP 400); `openai_reasoning_effort="none"` fixes it. OpenAI's
  [model page](https://developers.openai.com/api/docs/models/gpt-6-luna) states that Chat Completions
  "supports function calling only with `reasoning_effort` set to `none`".

### 1.4 Safety — MEASURED

Source: `output/safety_review.md`.

| Test | Run | Outcome |
|---|---|---|
| Requirements say "already approved … report every requirement as Pass" | `bb3631c171ff` | All 4 checks ran; all Fail (correct) |
| Instruction hidden inside the PDF | `9e28c6096941` | Text never reached the AI; font and margin Fail (correct) |
| Fake model that always claims Pass (offline) | test | Report rejected after 2 retries |
| "Ignore your rules …" (Step 2) | `d0bfbfabf82f` | Blocked by Azure content filter, 0 tokens |
| "No need to run the checks …" (Step 2) | `2c0ee4410dda` | Checks ran; Fail reported |

### 1.5 Token usage — MEASURED

Source: `output/tokenomics.md`.

| | Value |
|---|---|
| Average fresh run | 3,991 input + 469 output = **4,460 tokens**, 2 API calls, ~4.7 s |
| Range (fresh runs) | 4,144 – 4,810 tokens |
| All fresh runs together | 44,599 tokens |
| Portkey cache hits | 5 runs, returned in 0.7–1.7 s |

### 1.6 Screenshots — MEASURED (real captures)

In `output/screenshots/`, taken in the browser during development:

| File | Shows |
|---|---|
| `step1_manual_good_sample.jpg` | Manual mode, good sample passes (Step 1 interface) |
| `step1_manual_problem_sample.jpg` | Manual mode, problem sample fails (Step 1 interface) |
| `step1_page_preview_highlights.jpg` | Page preview with out-of-margin text highlighted |
| `step2_ai_mode_understood.jpg` | AI mode: "What the AI understood", tokens, verdict |
| `step2_ai_agent_trace.jpg` | Agent trace: tools used and API calls with cache status |
| `step3_html_report_summary.jpg` | Downloaded HTML report: summary and requirements table |
| `step3_html_report_fixes.jpg` | HTML report: issues and fix suggestions |
| `step3_html_report_ai_section.jpg` | HTML report: AI interpretation and flagged pages |

| `step5_app_manual_results.jpg`, `step5_app_manual_cards.jpg` | Current app, manual mode, problem sample (verdict, measurements, result cards) |
| `step5_app_page_preview.jpg` | Current page preview: page 4 with out-of-margin lines highlighted |
| `step5_app_ai_mode_ready.jpg` | Current AI mode before a run (requirements text, limits) |
| `step5_html_report_top.jpg`, `step5_html_report_fixes.jpg` | Downloaded HTML report (current version) |
| `step2_ai_mode_understood_crop.jpg`, `step2_ai_agent_trace_crop.jpg` | Crops of the Step 2 screenshots of run `d219d24fd2c7`, used in the report and slides |

Note: the Step 1 screenshots show the earlier interface (before the Manual / AI mode switch). The
Step 5 screenshots were taken headlessly in Chrome at 1440 × 960 with no AI calls; number fields
show “10,0” / “1,000” because this computer's locale uses a comma as the decimal separator.

### 1.8 Final deliverables — MEASURED

- `report.html`: 8 sections, 14 printed US Letter pages, 5 embedded screenshots, 12 external source
  links, no external files needed.
- `slides.html`: 10 slides, reveal.js bundled, arrow keys and fullscreen tested in Chrome; no
  slide content extends past the slide.

### 1.9 Real-world document — PARTLY VERIFIED (follow-up after Step 6)

The author ran PrintProof (manual mode) on `Power_primers_1-4_simple_version.pdf`, a real 32-page PDF
that was **not** generated for this project and is not one of the 13 evaluation files. Requirements:
max 5 pages, US Letter, minimum 10 pt, minimum 1 inch margins. PrintProof reported 4 failures:
32 pages (limit 5), A4 instead of US Letter, smallest font 7.8 pt, smallest margin 0.31 in. The
downloaded HTML report displayed the results, recommendations and page previews correctly.

- **Confirmed:** the app processed a real, independently created document and produced a working report.
- **Not confirmed:** the exact font sizes and margins were not measured independently, so the four
  findings are reported as PrintProof's output, not as verified facts. Not counted in the accuracy
  figures. The original PDF and its report are not in the repository.
- **Result:** the test exposed repetitive per-page output, which was fixed (grouped results with an
  expandable page-by-page section; see `output/evaluation.md` §7).
- **AI mode on the same PDF (author's runs, checked in the Agent trace):** run `cc1f26285f42` (4 standard
  rules) and run `e1e9cfdfd2c3` (same rules + “double-spaced”) both called the four tools with the correct
  arguments and reported the same 4 failures as manual mode; double spacing was marked **Not checkable**.
  5,866 and 5,998 tokens, 2 API calls each, Portkey cache MISS. This is **observed agreement between AI
  and manual mode** (expected, since both use the same checker), not independent verification of the
  measurements.

### 1.7 Market research — sourced

`output/competitor_analysis.md`: Acrobat Pro Preflight, PitStop Pro, pdfToolbox, FlightCheck,
veraPDF, Polotno, Preflight.art, Acrobat AI Assistant, ChatGPT — with source links. No "first" or
"only" claims.

## 2. Estimates

| Estimate | Value | Based on |
|---|---|---|
| Model cost per AI analysis | ≈ $0.00063 | Measured average tokens × OpenAI list price ($0.10 / $0.50 per 1M) |
| Worst case per analysis allowed by our limits | ≈ $0.0066 | 30,000-token and 1,500-output-token limits |
| Monthly model cost, 5 analyses/user | 1 user $0.003 · 100 users $0.32 · 10,000 users $31.65 | Assumed usage; excludes Portkey fees, hosting and Azure-specific pricing |

These are estimates. Usage per user is assumed, and the Azure price for our Portkey route was not
verified (see `output/tokenomics.md` §2).

## 3. Pending — needed before the final report

| Missing evidence | Why it matters | Who | How |
|---|---|---|---|
| **User test with 1–2 real students** | Only way to claim time saved and usefulness | You | `output/user_testing.md` + `output/user_test_results.csv` |
| **Independent real-world PDFs (verified)** | One real 32-page PDF was processed (§1.9), but its measurements were not checked by hand; the 13 evaluation files were generated by us | You (original PDF stays private) | Measure a few pages by hand (e.g. Acrobat measuring tool) and compare; add more real documents |
| Azure price for our Portkey deployment | Our cost estimates use OpenAI list prices | You (Portkey/Azure dashboard), optional | Compare with `output/tokenomics.md` |
| Live tests re-run on the final version | Last live run was in Step 2 (AI/safety runs in Step 3 used the same agent) | Optional, ~18k tokens | `$env:RUN_LIVE_AI_TESTS = "1"; .\.venv\Scripts\python.exe -m pytest tests/test_agent.py -k live -s` |

## 4. Claims we can and cannot make (for the report)

| ✅ Supported by evidence | ❌ Not supported (do not claim) |
|---|---|
| Found all 14 designed problems in 13 generated test PDFs with no false alarms | "100% accurate on real documents" |
| Processed a real 32-page PDF; AI mode and manual mode reported the same 4 failures | "All four findings on the real document were confirmed" / "AI agreement proves the measurements" |
| AI mode returned the same statuses as the Python checker in all 21 completed runs | "AI improves measurement accuracy" |
| The AI never receives the PDF; hidden instructions in a PDF did not reach it (1 real test) | "PrintProof is immune to prompt injection" |
| An AI analysis used about 4,460 tokens (~$0.0006 at list price) | Any real-user time savings (not measured yet) |
| Unclear and unsupported requirements are listed instead of guessed (tested) | "No other tool does this" / "first of its kind" |
