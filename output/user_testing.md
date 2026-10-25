# PrintProof AI — User testing (1–2 real students)

**Status: not run yet.** Every result field below is empty on purpose. Fill it in only with what
actually happened in the session. Results can also be typed into `output/user_test_results.csv`
(same columns, opens in Excel).

## What we want to learn

For the **same PDF**, checked first by hand and then with PrintProof:

1. How long does each method take?
2. Did PrintProof find the right problems (and only real ones)?
3. What does the student think of the app?

## 1. Before the session (facilitator, ~10 min)

1. Start the app from the Final Project folder and open http://localhost:8501:
   ```powershell
   .\.venv\Scripts\python.exe -m streamlit run app.py
   ```
2. **Choose the PDF(s).** Best: a real PDF the participant already has (for example their own
   assignment or a public course document), because our generated files are not independent
   evidence. Ask first, and use only files they are happy to share with you on screen.
   - Nothing from the PDF is uploaded anywhere in **Manual mode**. In **AI mode** only the
     requirements text, the file name and the measurements go to the AI; the audit log
     (`output/audit_trail.json`) stores the file name and a fingerprint (hash), not the content.
     Mention this to the participant. If the file name is personal, rename the copy first.
   - Backup if they have no PDF: one of our generated files from `tests/eval_pdfs/` (e.g.
     `c04_tiny_table.pdf`). Mark these rows as "generated file" — they are not real-world evidence.
3. Decide the rules to check. Default (read them to the participant):

   > At most **5 pages**, **US Letter** paper, **no text smaller than 10 pt**,
   > **at least 1 inch margins** on every side.

   If the participant's course has its own rules, use those instead and write them in the form.
4. Have a stopwatch ready (phone). Record initials only — no names, emails or student IDs.

## 2. Session (~15 minutes per document)

| Step | What to do | What to record |
|---|---|---|
| 1. Intro (1 min) | "I'm timing two ways of checking a PDF. I'm testing the app, not you. You can stop anytime." | Consent: yes/no |
| 2. **Manual check** | Participant opens the PDF in any viewer they normally use and checks each rule (zoom, document properties, Acrobat Measure tool, ruler — their choice). Start timing when the PDF opens; stop when they finish their answer for all rules. | Time (mm:ss), method used, their answer per rule (pass/fail + pages) |
| 3. Short demo (1 min) | Show the app on `sample_pdfs/good_sample.pdf`, **not** on their file. | — |
| 4. **PrintProof check** | Participant uploads the **same PDF** and checks the same rules, in Manual mode (or AI mode if they prefer to type the rules). Start timing at upload; stop when they say their final answer. | Time (mm:ss), mode used, PrintProof's result per rule |
| 5. Decide the correct answer | For every rule where the two answers differ, the facilitator checks that part of the PDF carefully (e.g. Acrobat Measure tool or zoomed preview) and writes down which answer was right. | Correct answer per rule, who was right |
| 6. Questions (3 min) | Ask the questions in section 4 and write down their words. | Ratings and comments |

**Known bias:** the manual check always comes first, so by the time they use PrintProof they
already know the document. This makes the PrintProof time slightly *shorter* than for a fresh
document — mention it in the report. (Swapping the order would make manual checking look faster for
the same reason, so with the same document there is no perfect order.)

## 3. Recording form

### 3a. Session

| Field | Participant 1 | Participant 2 |
|---|---|---|
| Initials | | |
| Date | | |
| Consent given | | |
| Program / year | | |
| Experience with PDF tools (1 = none … 5 = expert) | | |
| Document used (short description, not the file name if personal) | | |
| Real document or generated test file? | | |
| Number of pages | | |
| Rules checked | | |

### 3b. Time

| Participant | Manual method used | Manual time (mm:ss) | PrintProof mode (Manual/AI) | PrintProof time (mm:ss) | Difference (manual − PrintProof) |
|---|---|---|---|---|---|
| 1 | | | | | |
| 2 | | | | | |

### 3c. Results per rule

Use Pass / Fail / Needs Review and page numbers.

| Participant | Rule | Participant's manual answer | PrintProof result | Correct answer (after checking differences) | Manual correct? | PrintProof correct? |
|---|---|---|---|---|---|---|
| 1 | Max pages | | | | | |
| 1 | Paper size | | | | | |
| 1 | Min font size | | | | | |
| 1 | Margins | | | | | |
| 2 | Max pages | | | | | |
| 2 | Paper size | | | | | |
| 2 | Min font size | | | | | |
| 2 | Margins | | | | | |

### 3d. Summary (calculate from the tables above)

| Measure | Manual | PrintProof |
|---|---|---|
| Average time per document | | |
| Rules answered correctly | / | / |
| Real problems missed | | |
| Problems reported that were not real | | |
| "Needs Review" results (PrintProof could not decide) | — | |

## 4. Questions after the session

| Question | Participant 1 | Participant 2 |
|---|---|---|
| How confident were you in your manual answer? (1–5) | | |
| How confident are you in PrintProof's answer? (1–5) | | |
| How easy was PrintProof to use? (1–5) | | |
| Was anything confusing or wrong? | | |
| Was the fix advice / HTML report useful? | | |
| Would you use it before submitting? (yes / no / maybe — why) | | |
| What would you change or add? | | |

## 5. How to use the results in the report

- Report the real numbers, including cases where manual checking was faster or PrintProof was wrong.
- With 1–2 participants the result is an **example**, not a reliable average. Say so.
- Keep generated test files separate from real documents when describing accuracy.
