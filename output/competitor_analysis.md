# PrintProof AI — Competitor analysis (Step 4)

Research done on 2026-10-25 using the vendors' own pages where possible. Each claim below is linked
to its source. Where a page could not be opened directly (Adobe's help pages blocked automated
access), the information comes from Adobe's own pages as shown in search results; those links are
marked "(search result)". Features and prices change — check the source before quoting a number.

**Scope note:** this is a short desk review, not an exhaustive market study. Not finding a product
in our search does **not** mean no such product exists, so we make no "first" or "only" claims.

## 1. Existing tools

### Professional print preflight (prepress)

| Tool | What it does (from the source) | Price / access | Source |
|---|---|---|---|
| **Adobe Acrobat Pro – Preflight** | Predefined preflight **profiles** (e.g. Digital Printing, Prepress, PDF/A, PDF/X), each made of **checks**; users can create **custom checks**. Checks can compare a property such as **text size** with a value you enter, and cover **page sizes and page boxes** (media, bleed, trim, art box). **Fixups** correct some problems automatically. Results can be saved as **PDF, XML or text reports**; a detailed PDF report marks problem objects. Batch processing with droplets/actions. | Part of Acrobat Pro (paid subscription) | [Preflight profiles](https://helpx.adobe.com/acrobat/using/preflight-profiles-acrobat-pro.html) (search result) · [Additional checks](https://helpx.adobe.com/ie/acrobat/using/additional-checks-preflight-tool-acrobat.html) (search result) · [Preflight reports](https://helpx.adobe.com/acrobat/using/preflight-reports-acrobat-pro.html) (search result) · [Fixups](https://helpx.adobe.com/acrobat/current/correcting-problem-areas-preflight-tool.html) (search result) |
| **Enfocus PitStop Pro** | Acrobat plug-in (Mac/Windows) that "detects errors, applies automatic fixes, and generates a report with visual highlights". Checks include fonts, image resolution, color spaces, ink coverage, bleed, transparency/overprint, hidden content, **incorrect document size** and PDF/X compliance. Extensive manual PDF editing and reusable Action Lists. Lists an AI feature for "visual checking" of missing key images or logos. | Page listed $40/month or $480/year (ex. VAT); 30-day trial | [enfocus.com/en/pitstop-pro](https://www.enfocus.com/en/pitstop-pro) |
| **callas pdfToolbox** | "Quality control … based on preflight profiles"; "can automatically correct many of those issues"; reports as PDF, XML or JSON; editions: Desktop (Acrobat plug-in or standalone), Server (hot folders), CLI, SDK; supports PDF/X, PDF/A, PDF/UA. Rule logic can be scripted in JavaScript. No AI or natural-language feature mentioned. | No prices listed; 14-day trial | [callassoftware.com/products/pdftoolbox](https://callassoftware.com/products/pdftoolbox/) |
| **Markzware FlightCheck** | Standalone macOS app to preview, preflight, report and package PDF and design files (InDesign, QuarkXPress); checks fonts, images, colors; PDF/X validation based on Ghent Workgroup specs. | Commercial | [CreativePro (FlightCheck 5.8)](https://creativepro.com/pdf-preflight-pioneer-markzware-jumps-ahead-releases-flightcheck-professional-5-8-with-ghent-pdf-workgroup-pdf-x-plus-sp/) · [PIWorld (2024)](https://piworld.com/article/markzware-flightcheck-preflights-adobe-creative-cloud-2024) |
| **veraPDF** | Free, open-source validator for the **PDF/A** archiving standard, led by the Open Preservation Foundation and the PDF Association. | Free | [Flathub listing](https://flathub.org/en/apps/org.verapdf.veraPDF) |

### Free / online and AI-branded checkers

| Tool | What it does (from the source) | Price | Source |
|---|---|---|---|
| **Polotno PDF preflight checker** | Runs in the browser, "file never leaves your machine". Checks page geometry (consistent sizes, TrimBox, bleed, rotation, standard size) and content (embedded fonts, RGB/CMYK, spot inks, overprint, transparency). States what it cannot check (true image DPI, ink coverage, PDF/X conformance). No minimum font size or general margin rule mentioned. | Free | [polotno.com/tools/pdf-preflight](https://polotno.com/tools/pdf-preflight) |
| **Preflight.art** | "The AI preflight for packaging artwork": PDF/AI/EPS up to 75 MB; checks color, spelling, spot colors, dielines, bleed/safe zone, **fonts and minimum text size**, DPI, ink, barcodes, white ink; "plain-language fixes"; profiles for labels and packaging. The page does not describe entering custom requirements in plain English. Reports are "advisory". | 5 free checks; $79.99/seat/month; enterprise | [preflight.art](https://preflight.art/) |
| **Adobe Acrobat AI Assistant** | Ask questions about a PDF and get answers with citations to the document; generative summaries. Limited free requests; add-on subscription for full access. Adobe's documentation describes content Q&A and summaries; we found no description of measuring layout (font size, margins) against rules. | Free (limited) / add-on | [Get answers in your PDF](https://helpx.adobe.com/acrobat/desktop/use-acrobat-ai/generative-ai-features/ai-get-answers.html) (search result) · [Acrobat AI Assistant](https://www.adobe.com/acrobat/generative-ai-pdf.html) (search result) |
| **General chatbots (e.g. ChatGPT)** | Can analyze uploaded PDFs and run Python code for analysis; OpenAI advises to "review the generated code, outputs, and assumptions" and warns that exact values from scanned files may not be reliable. A user *could* ask it to check margins, but the method changes per conversation and is not built for this task. | Subscription / free tiers | [Data analysis with ChatGPT](https://help.openai.com/en/articles/8437071-data-analysis-with-chatgpt) (search result) · [File uploads FAQ](https://help.openai.com/en/articles/8555545-file-uploads-faq) (search result) |

### How students check today (academic submissions)

Graduate schools publish formatting **checklists** (margins, headings, page numbering, spacing) that
the author confirms item by item — for example the
[University of Utah formatting checklist](https://gradschool.utah.edu/thesis/templates-guides-samples/formatting-checklist.php)
(side margins "1 ¼ inches", main headings "2 inches from the top") and the
[South Dakota Mines thesis checklist](https://sdsmt.edu/experience/graduate-education/assets/Thesis-Dissertation-Format-Checklist.pdf) (search result).
In our search we did not find an automated checker offered by these schools; the checklists are
completed by hand. Rules also differ between schools, which is why typed, flexible requirements matter.

## 2. Comparison with PrintProof

| Capability | Acrobat Preflight | PitStop Pro / pdfToolbox | Free online checkers | AI chat with PDF | **PrintProof** |
|---|---|---|---|---|---|
| Built for | Print production | Print production | Print shops / designers | Questions about content | **Students & office users submitting documents** |
| Page count limit | Not confirmed in our sources | Not confirmed | Not mentioned | Ask the chatbot | ✅ |
| Page size (Letter/A4) | ✅ page/box size checks | ✅ document size | ✅ (Polotno) | Ask the chatbot | ✅ (Letter, A4; other sizes identified) |
| Minimum text size | ✅ text size property | Not confirmed in our sources | Preflight.art ✅ | Ask the chatbot | ✅ |
| Margins (content distance to the edge) | Possible via custom checks (trim/box distance) — not confirmed as a simple setting | Not confirmed | Bleed / safe zone | Ask the chatbot | ✅ per side, per page |
| Color, bleed, ink, resolution, PDF/X | ✅ | ✅ | Partly | — | ❌ not supported |
| Automatic fixes | ✅ fixups | ✅ | — | — | ❌ advice only |
| Requirements typed in plain English | ❌ (profiles/checks set in dialogs) | ❌ (profiles; scripting) | ❌ fixed checks | ✅ free text, but measurement method not fixed | ✅ mapped to fixed Python checks |
| Says "Needs Review" / "Not checked" instead of guessing | Errors/warnings per check | Errors/warnings | Polotno lists checks it can't do | Not guaranteed | ✅ built in |
| Same document → same result | ✅ deterministic | ✅ | ✅ | Not guaranteed | ✅ measurements are deterministic Python |
| PDF content sent to an AI | — | — | No (Polotno local) | Yes | **No** — only numbers |
| Price | Acrobat Pro subscription | $480/yr (PitStop); quote (callas) | Free – $79.99/mo | Free–paid | Free (manual) · ≈$0.0006 per AI check (see `tokenomics.md`) |
| Maturity | Industry standard | Industry standard | Products | Products | Class prototype, tested on generated files only |

"Not confirmed" means our sources did not mention it — it may still exist.

## 3. What makes PrintProof different (and what doesn't)

**Different in combination, not "first":**

1. **Target user and rule set.** Professional preflight tools focus on print production (color,
   bleed, ink, PDF/X). PrintProof focuses on the simple rules that matter for submitting a paper:
   page limit, paper size, minimum font size and margins, reported page by page with fix advice.
2. **Plain-English requirements → fixed, real tools.** A student can paste "A4 paper only, at most
   five pages, nothing smaller than 10pt, 20 mm margins" (tested in Step 3, run `e976db5da5cd`).
   The AI only translates the text into tool calls; the measurement is done by the same Python code
   every time. This differs from:
   - preflight tools, where rules are set up in profile dialogs or scripts, and
   - general chatbots, which can read a PDF but decide how to measure in each conversation.
3. **Honesty by design.** Unclear rules ("normal margins") and unsupported ones ("double spaced")
   are listed instead of guessed; scanned pages are "Needs Review"; the AI report is rejected if it
   disagrees with the measurements.
4. **The AI never sees the document**, which keeps costs low (~4,500 tokens per check) and blocks
   instructions hidden inside PDFs (Step 3 safety test `9e28c6096941`).

**Where competitors are clearly stronger:**

- Far more checks (color, fonts embedded, resolution, bleed, transparency, standards like PDF/X and
  PDF/A) and certified validation.
- Automatic fixing of problems; PrintProof only explains how to fix them.
- Batch processing, server automation, integrations, and years of real-world use. PrintProof has
  been evaluated only on 13 generated test files so far.

**Positioning in one sentence:** PrintProof is not a replacement for professional preflight; it is a
lightweight checker for everyday submission rules that lets people state those rules the way they
received them, while keeping the actual checking deterministic and transparent.
