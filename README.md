# PrintProof AI

MGT 409 (AI Foundations for Managers) final project · Beck Jamilov · Yale SOM, Fall 2026

PrintProof AI checks whether a PDF is ready to print or submit. You upload a PDF, give the
requirements — with switches (**Manual mode**) or in plain English (**AI mode**) — and the app
measures the real file and reports **Pass**, **Fail** or **Needs Review** for each requirement, with
the actual measurements, the page numbers where problems were found, and fix suggestions.

It checks four kinds of rules: maximum number of pages, paper size (US Letter or A4), minimum font
size and minimum margins. The measuring is always done by Python (PyMuPDF); in AI mode a PydanticAI
agent using **gpt-6-luna through Portkey** only translates the written requirements into these checks.

- **Final report:** [`report.html`](report.html) · **Slides:** [`slides.html`](slides.html)
  (download and open by double-clicking; everything is embedded)
- **Repository:** https://github.com/BeckJamilov/printproof-ai
- **App link:** none — the app runs locally (see Quick start)

## Quick start (Windows PowerShell)

Requires **Python 3.12 or newer** (tested with Python 3.14.7) and **Git**.

**1. Get the code**

```powershell
git clone https://github.com/BeckJamilov/printproof-ai.git
cd printproof-ai
```

**2. Create a virtual environment and install the dependencies** (takes about 1–2 minutes)

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

If `py` is not found, use `python -m venv .venv` instead. All other commands call the virtual
environment's Python directly, so you never need to activate it.

**3. Add the Portkey API key** (only needed for AI mode)

The app reads `PORTKEY_API_KEY` from a `.env` file. It looks in the project folder first and then
in the **folder one level above**, so either of these works:

```
some-folder/
├── .env                 ← option A: .env one folder above the project
└── printproof-ai/
    ├── .env             ← option B: .env inside the project (copy .env.example)
    └── app.py
```

The `.env` file contains one line:

```
PORTKEY_API_KEY=your-portkey-api-key-here
```

To create option B from the template: `Copy-Item .env.example .env` and then edit the key.
`.env` is in `.gitignore` and is never committed. Manual mode works without any key.

**4. Start the app**

```powershell
.\.venv\Scripts\python.exe -m streamlit run app.py
```

When PowerShell shows `You can now view your Streamlit app in your browser`, open
**http://localhost:8501** in your browser. (The project's `.streamlit/config.toml` starts Streamlit
without its first-run email question and without opening a tab automatically.) Stop the app with
**Ctrl+C** in PowerShell.

## How to use it

### Manual mode (no API key needed)

1. Leave **Check mode** on **Manual** in the left sidebar.
2. Turn on the requirements you need and set the values (default: max 5 pages, US Letter,
   minimum 10 pt text, 1 inch margins).
3. Upload a PDF — or click **✅ Good sample** or **⚠️ Problem sample** to try the included files.
4. Read the verdict and the result cards. When the same problem appears on many pages it is
   reported once (e.g. "All 32 pages are A4 … — not US Letter"), with the smallest measurement,
   the affected pages and a few examples; open **Page-by-page details** on a card to see every page.
   The tabs show a **Page preview** (problem areas highlighted) and **Page-by-page data**.
5. Click **⬇ Download HTML report** for a standalone report with fix suggestions.

### AI mode (needs `PORTKEY_API_KEY`)

1. Switch **Check mode** to **AI · plain English**.
2. Type or paste the rules as you received them, for example
   *"maximum 5 pages, US Letter paper, at least 10 pt font and 1 inch margins"* or
   *"A4 only, no more than 6 pages, 20 mm margins, double spaced"*.
3. Load a PDF (upload or a sample button) and click **✨ Run AI analysis**.
4. The app shows **What the AI understood** (including rules it cannot check, such as double
   spacing), the measured results with an AI explanation for each, and an **Agent trace** tab with
   the tools called, the API calls, tokens and Portkey cache status.

One AI analysis makes 2 API calls and uses about 4,500 tokens (measured average 4,460). Limits per
analysis: 6 API calls, 8 tool calls, 30,000 tokens. Only the requirements text and the measurements
are sent to the AI — never the PDF or its text. Each run is appended to `output/audit_trail.json`.

## Run the tests

Offline tests (free, no API calls, about 10 seconds):

```powershell
.\.venv\Scripts\python.exe -m pytest
```

Expected result: `69 passed, 4 skipped`. The 4 skipped tests make real Portkey calls and only run
on request (about 4,000–5,000 tokens each):

```powershell
$env:RUN_LIVE_AI_TESTS = "1"; .\.venv\Scripts\python.exe -m pytest tests/test_agent.py -k live -s
```

Re-run the evaluation on the 13 test PDFs (free):

```powershell
.\.venv\Scripts\python.exe tests/evaluation.py
```

## Troubleshooting

| Problem | Fix |
|---|---|
| `python` or `py` opens the Microsoft Store / "Python was not found" | Install Python from python.org (includes the `py` launcher), then repeat step 2 |
| `streamlit : The term 'streamlit' is not recognized` | Use the full command from step 4 (`.\.venv\Scripts\python.exe -m streamlit run app.py`) |
| Sidebar says "Portkey key not found" | Check that `.env` is in the project folder or the folder directly above it, and that the line starts with `PORTKEY_API_KEY=` |
| Port 8501 is already in use | `.\.venv\Scripts\python.exe -m streamlit run app.py --server.port 8502` |
| `git clone` or `pip install` fails with "Filename too long" | Clone into a short path such as `C:\Users\<you>\printproof-ai`; Windows limits paths to 260 characters |

## How it works

| File | Role |
|---|---|
| `app.py` | Streamlit interface: manual mode, AI mode, results, page preview, report download |
| `pdf_checker.py` | Measures the PDF with PyMuPDF: page count, page size, text sizes, distance of content to each edge; detects scanned pages |
| `tools.py` | The checks the AI may call; return numbers only (PDF text is removed) |
| `agent.py` | PydanticAI agent, Portkey/gpt-6-luna model, limits, output validator, audit trail |
| `models.py` | Structured output (`PrintProofReport`) and run data |
| `prompts/prompt.md` | Agent instructions |
| `report.py` | Standalone HTML report with fix suggestions |

**How the AI is kept honest:** the AI never sees the PDF; an output validator rejects any report
whose statuses differ from the tool results; unclear or unsupported requirements are listed instead
of guessed. gpt-6-luna is used with `reasoning_effort="none"` because Chat Completions only supports
function calling with that setting
([OpenAI model page](https://developers.openai.com/api/docs/models/gpt-6-luna)).

## Evidence and evaluation

Start with [`output/project_evidence.md`](output/project_evidence.md) — it separates measured
results, estimates and pending items.

| File | Contents |
|---|---|
| `output/evaluation.md`, `output/evaluation_results.json` | 13 test PDFs, 52 checks, expected results recorded before testing; manual vs AI mode |
| `output/safety_review.md` | Protections and real attack tests |
| `output/tokenomics.md` | Real token usage, Portkey cache hits, cost estimates |
| `output/competitor_analysis.md` | Existing tools vs PrintProof, with sources |
| `output/audit_trail.json` | Append-only log of every AI run |
| `output/user_testing.md`, `output/user_test_results.csv` | Student test procedure and form — **results still pending** |
| `output/final_checklist.md` | Final submission checks |
| `output/screenshots/` | Real screenshots |
| `tests/eval_expected.json`, `tests/eval_pdfs/` | Expected results and the 13 test PDFs |
| `AI_prompts.md` | Every prompt used to build the project, by step |

**Still pending:** testing with independent real-world PDFs and with real students. The evaluation
PDFs were generated by us, so no accuracy claim is made for real documents.

## Project structure

```
printproof-ai/
├── app.py, pdf_checker.py, agent.py, tools.py, models.py, report.py
├── prompts/prompt.md
├── sample_pdfs/            good_sample.pdf, bad_sample.pdf
├── tests/                  test_*.py, evaluation.py, eval_expected.json, eval_pdfs/ (13 PDFs)
├── output/                 evidence, audit trail, screenshots, checklists
├── report.html             final report (standalone)
├── slides.html             final presentation (standalone, reveal.js 5.2.1 bundled, MIT license)
├── .streamlit/config.toml  starts Streamlit without the first-run prompt
├── requirements.txt, .env.example, .gitignore
├── AI_prompts.md
└── README.md
```
