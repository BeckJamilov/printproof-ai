# PrintProof AI — Tokenomics (Step 4)

**Measured** numbers come from `output/audit_trail.json` (17 AI runs recorded from 2026-10-25,
Steps 2–3). **Estimates** are labeled and their assumptions are listed. Prices were checked on
OpenAI's official pages on 2026-10-25.

## 1. What one AI analysis looks like (measured)

Every completed analysis used the same pattern: **2 API calls**.

1. Call 1: the model reads the instructions + the requirements and asks for the check tools.
2. Call 2: the model receives the tool results (numbers only) and writes the structured report.

### All 17 recorded runs

| Type | Runs | What it means |
|---|---|---|
| Fresh runs (real model work) | **10** | Portkey cache MISS or no cache evidence |
| Portkey cache hits | **5** | Identical request answered from Portkey's cache (3 identified afterwards by duplicate response IDs, 2 recorded as `HIT`) |
| Rejected before the model ran | **2** | HTTP 400: reasoning + tools not allowed (Step 2 test), and Azure content filter. 0 tokens |

Cache status (`x-portkey-cache-status`) has been recorded for every API call since run
`a0e1c7572d62` (16 calls so far).

### Tokens per fresh run (10 runs)

| Measure | Mean | Median | Min | Max | Total (10 runs) |
|---|---|---|---|---|---|
| Input tokens | 3,991 | 3,984 | 3,770 | 4,194 | 39,913 |
| Output tokens | 469 | 453 | 308 | 616 | 4,686 |
| **Total tokens** | **4,460** | 4,460 | 4,144 | 4,810 | **44,599** |
| API calls | 2 | 2 | 2 | 2 | 20 |
| Tool calls | 3.5 | 4 | 1 | 4 | 35 |
| Run time (s) | 4.7 | 4.7 | 3.85 | 6.05 | — |

Per call (fresh runs):

| | Input tokens (mean) | Output tokens (mean) |
|---|---|---|
| Call 1 — read requirements, choose tools | 1,810 | 83 |
| Call 2 — read tool results, write report | 2,182 | 386 |

**Observation:** about 90% of tokens are **input**, and most of that is the same agent instructions
(`prompts/prompt.md`) and tool/output definitions sent twice. The PDF itself is never sent, so the
token count barely depends on document length: only the lists of problem page numbers grow (detail
lines are capped at 10 per check). The runs above used 1–8 page documents; a later run on a 32-page
document used about 1,000 more input tokens (see §7).

Cache hits returned the same token counts as the original call (4,364–4,632) in 0.7–1.7 s.

## 2. Price used (verified)

From [OpenAI API pricing](https://developers.openai.com/api/docs/pricing) and the
[gpt-6-luna model page](https://developers.openai.com/api/docs/models/gpt-6-luna) (checked 2026-10-25):

| gpt-6-luna, Standard, per 1M tokens | Price |
|---|---|
| Input | $0.10 |
| Cached input | $0.01 |
| Output | $0.50 |

### Assumptions (important)

1. **Provider price.** Our Portkey key routes requests to **Azure OpenAI** (response header
   `x-portkey-provider: azure-openai`). Azure's price for this deployment was not verified; we use
   OpenAI's list price as the estimate.
2. **Portkey fees** and **hosting** (running the Streamlit app) are **not** included.
3. **Cache hits** are assumed to cost nothing at the model provider, because Portkey answers them
   without calling the model. Provider-side prompt caching (cheaper cached input) was **not** measured,
   so all input is priced at the full $0.10 rate — this makes the estimates slightly high, not low.
4. **Usage per user** is an assumption (no real usage data yet): typical = **5 AI analyses per
   month** (check, fix, re-check a few assignments), heavy = **20 per month**.

## 3. Cost per analysis

| | Input cost | Output cost | Total |
|---|---|---|---|
| Average fresh run (3,991 in / 469 out) | $0.00040 | $0.00023 | **$0.00063** |
| Most expensive observed run (4,194 in / 616 out) | $0.00042 | $0.00031 | $0.00073 |
| Worst case allowed by our limits (≈21,000 in / 9,000 out, see §5) | $0.0021 | $0.0045 | **≈ $0.0066** |
| Manual mode | — | — | **$0** (no API call) |

**Actually spent so far:** 10 fresh runs ≈ **$0.0063** (less than one cent) at list price.

## 4. Estimated monthly cost (estimates, based on the measured average)

| Users | Typical (5 analyses/user/month) | Heavy (20/user/month) | Worst case at the limits (5/user/month) |
|---|---|---|---|
| 1 | $0.003 | $0.013 | $0.033 |
| 100 | $0.32 | $1.27 | $3.30 |
| 10,000 | **$31.65** | $126.60 | $330.00 |

Formula: users × analyses × $0.000633 (typical/heavy) or × $0.0066 (worst case).

At these volumes the **model cost is small**; hosting, Portkey, support and storage would probably
cost more at 10,000 users (not estimated here).

## 5. How we kept costs down — and the tradeoffs

| Measure | Saves | Tradeoff |
|---|---|---|
| The PDF is never sent to the AI; tools return only numbers | Cost stays ~4,500 tokens regardless of document length; also privacy and prompt-injection safety | The AI cannot "look" at the document, so it cannot judge anything the Python checker doesn't measure |
| Measurement done in Python, AI only interprets and explains | No tokens spent on measurement; manual mode is free | AI adds no measurement accuracy |
| `request_limit = 6` API calls per run (typical run uses 2) | Stops runaway loops | Leaves room for only a few retries if the model makes mistakes |
| `tool_calls_limit = 8` (typical 4) | Caps tool loops | A very long list of rules could hit the cap; today only 4 checks exist, so this is unlikely |
| `total_tokens_limit = 30,000` (typical 4,460) | Caps the worst case at about $0.0066 per run | None seen in practice (largest run 4,810) |
| `max_tokens = 1,500` per response (largest observed 616 for a whole report) | Caps long answers | A report for many rules with long explanations could be cut off |
| Requirements limited to 1,000 characters | Caps input size | Long syllabus pages must be shortened to the relevant rules |
| AI runs only when the user clicks "Run AI analysis" | No accidental re-runs when settings change | The user must click again after editing the text |
| `reasoning_effort = "none"` | Fewer output tokens and faster replies; required for tool calls on Chat Completions | Less step-by-step reasoning for complicated or ambiguous rules. OpenAI documents that tool calls with reasoning are possible through the Responses API — a possible upgrade at higher cost |
| Portkey cache | Identical repeated requests cost nothing extra and return in ~1 s | Only helps exact repeats (same file name and same text), so real users will rarely benefit |

**Possible further savings (not implemented):** shorter instructions (the prompt is the largest input
cost), sending the tool list only once (a single-call design), or skipping the AI completely when the
requirements are already set with the manual controls.

## 6. Is AI mode worth it?

| | Manual mode | AI mode |
|---|---|---|
| Measurement accuracy | Python checker | **Same** Python checker — no accuracy gain |
| Cost per check | $0 | ≈ $0.0006 |
| Time for the computer | ~0.01 s | ~4–6 s (≈1 s if cached) |
| Needs internet + Portkey key | No | Yes |
| Typing requirements | Set 4 controls by hand | Paste the rules as written |
| Units, wording ("20 mm", "one-inch", "Letter size") | User converts | Understood automatically (conversion still in Python) |
| Unclear / unsupported rules ("normal margins", "double spaced") | Cannot be entered, silently ignored | Listed as needing clarification or a manual check |
| Explanations | Measurements + details | Plus a plain-English explanation per check and a summary |

**Conclusion:** the money cost of AI mode is negligible (well under a tenth of a cent per check), so
the question is usefulness, not price. AI mode is worth using when requirements come as text (a
syllabus, a printer's email), use mixed units, or include rules PrintProof cannot check, because it
makes those visible instead of silently skipping them. For a student who already knows the four
numbers, manual mode is faster, free, works offline, and gives exactly the same results.
Whether real users actually prefer AI mode has **not** been measured yet (see `output/user_testing.md`).

## 7. Runs after this analysis (Step 6 and follow-up)

The statistics above cover the 17 runs of Steps 2–3. Later runs, all in `output/audit_trail.json`:

| Run | Purpose | Tokens (in / out) | Portkey cache |
|---|---|---|---|
| `0b134c84cd88` | Fresh-install test (local clean clone) | 4,632 (4,081 / 551) | HIT, HIT → 0 new model tokens |
| `b8b8cf05907f` | Fresh-clone test from GitHub | 4,632 (4,081 / 551) | HIT, HIT → 0 new model tokens |
| `6685105933e6` | AI mode on a generated 32-page test document | **5,532 (5,008 / 524)** | MISS, MISS |

The 32-page run shows that token use does grow somewhat with document length: the tool results list
more problem page numbers (detail lines are capped at 10 per check). At list price this run cost about
$0.0008 instead of the $0.0006 average — still well under a tenth of a cent.
