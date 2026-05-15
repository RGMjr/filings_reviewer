# Worker prompt — gh-612 section_classification variant gap

## Context

During Phase-2 gate run `20260511T1416live`, 6 of 55 filings
returned **zero paraphrase segments** because `section_classification`
detected no whitelisted sections (MDA, Business, Risk Factors). Each
of these wrapped pipeline in 3–7 seconds vs. the typical 9–15
minutes, confirming the paraphrase path was inert.

The gh-574 fix (retain short paragraphs that carry an `<a name>` or
`<a id>` anchor target) addressed the Datadog/Chewy heading shape —
**but at least one other heading-markup variant slipped through**.
This worker identifies the variant and extends the fix.

Approximately **11% of the Phase-2 corpus** was affected, which
silently biases gate measurements: filings with zero paraphrase
segments cannot contribute classifier-only positives, so the
classifier's actual contribution is under-measured.

## The 6 affected filings

| filing_id | R2 key | Size | Sections detected |
|---|---|---|---|
| 209382 | `filings/0001790625/0001213900-21-064292/primary.htm` | 12 MB | `{COVER: 0}` |
| 215071 | `filings/0001840199/0001213900-22-059005/primary.htm` | 4.5 MB | `{COVER: 0, FINANCIALS: 1}` |
| 833 | `filings/0001703956/0001437749-19-008842/primary.htm` | 6 MB | (zero whitelisted) |
| 10273 | `filings/0001330421/0001330421-16-000057/primary.htm` | 2.5 MB | (zero whitelisted) |
| 192171 | `filings/0001772757/0001104659-20-112736/primary.htm` | 7.7 MB | (zero whitelisted) |
| 207445 | `filings/0001816581/0001193125-21-247997/primary.htm` | 4.7 MB | (zero whitelisted) |

All 6 are reviewed-corpus filings with non-zero text-source review
decisions in the DB — fetch via `_resolve_filing_html` from
`scripts/run_phase1_eval.py` or directly from R2 with the keys above.

## What to build

### Step 1 — Investigate the heading markup (DO NOT GUESS)

For each of the 6 filings:

1. Fetch the HTML (R2 or filesystem).
2. Search the raw HTML for the strings "MANAGEMENT'S DISCUSSION",
   "Risk Factors", "Risk Factors Summary", "Description of Business",
   "Item 1A", "Item 7", "ITEM 7", etc. — wherever these appear as
   actual section headings (not just in-prose mentions or TOC entries).
3. Record the surrounding HTML markup (5–10 lines of context around
   each heading). Capture:
   - The HTML tag (`<p>`, `<h1>`, `<h2>`, `<font>`, `<span>`, etc.)
   - Any nested formatting (`<b>`, `<strong>`, `<center>`,
     `<font size=...>`, inline CSS)
   - Anchor markup (`<a name>`, `<a id>`, `id=...`)
   - The exact text content and its character count
4. Cross-reference what `IngestionStage._extract_paragraph_segments_with_elements`
   does with that markup. Specifically: does the heading text survive
   to a Segment, and if so, what does the Segment's `text` and
   `segment_type` look like? If it gets dropped, what predicate drops
   it?

**Write up the findings before writing any code.** Add a "Root cause"
section to the gh-612 fragment (`docs/known-issues/gh-612-...md`)
with concrete line citations and HTML snippets. The fix must follow
from the observed markup, not from a hypothesis.

### Step 2 — Implement the fix

Based on the findings:

- **If the heading is dropped by an existing predicate**: extend the
  retention logic (in `_extract_paragraph_segments_with_elements`,
  alongside the gh-574 anchor-retention rule) to admit the variant.
  Prefer surgical predicates that match the observed pattern, not
  broad relaxations that risk pulling in TOC entries / footnotes /
  page numbers.

- **If the heading IS extracted as a Segment but `SECTION_PATTERNS`
  doesn't match**: extend the regex set in
  `src/extraction_v2/stages/section_classification.py::SECTION_PATTERNS`
  with the observed pattern. Use anchored matching (`^...$`) and
  case-sensitive flags consistent with existing patterns.

- **If the heading is extracted but `_is_section_heading()` rejects
  it** (e.g., text too long, fails uppercase predicate): relax the
  predicate only as much as the observed evidence warrants. Add a
  test that exercises the boundary.

Whatever the fix shape, it must be **additive** — long, canonical
headings (covered by current rules) must still work; the Datadog
gh-574 case must still work.

### Step 3 — Add an operator-visible diagnostic

In `scripts/run_phase2_quantitative_eval.py` (or the Phase-1 helper
that runs the pipeline, depending on where it fits cleanest), after
section_classification runs, emit a warning to the log if a filing
has:

- `n_segments ≥ 1000`, AND
- Zero whitelisted sections detected (MDA + Business + Risk Factors
  all zero)

Surface this in `summary.json` under
`summary.section_classification_warnings` as a list of
`{filing_id, filing_url, n_segments, detected_sections}` records.

Operators reading the summary should be able to tell at a glance
that filings X, Y, Z had inert paraphrase paths, so they can decide
whether the gate result is trustworthy or biased by this gap.

### Step 4 — Validate post-fix

For each of the 6 affected filings, run a smoke check:

```python
from src.extraction_v2.pipeline import V2Pipeline, PipelineConfig
from scripts import run_phase1_eval as p1
# ... fetch HTML for the filing ...
config = PipelineConfig(enable_llm_presence_classifier=False, retain_context=True)
result = V2Pipeline(config=config).process(html_path=..., filing_id=..., ...)
sections = result.context.section_counts  # or whatever surfaces it
assert sections.get('MDA', 0) >= 1 or sections.get('BUSINESS', 0) >= 1 or sections.get('RISK_FACTORS', 0) >= 1, \
    f"Filing {filing_id} still has no whitelisted sections"
```

Acceptance: all 6 filings detect at least one whitelisted section
post-fix. If any still don't, the variant is more diverse than
expected — flag and present findings rather than push a partial fix.

### Step 5 — Test coverage

- Unit test in `tests/unit/extraction_v2/test_ingestion.py` (or
  `test_section_classification.py`, whichever the fix lives in) with
  a minimized HTML snippet reproducing the variant heading markup
  observed in one of the 6 filings. Assert the section is detected.
- Regression test: a minimal Datadog-style HTML snippet (anchor-name
  short paragraph) still produces an MDA detection.
- Regression test: a minimal canonical heading (`<p>MANAGEMENT'S
  DISCUSSION AND ANALYSIS</p>` long-form) still produces an MDA
  detection.
- Test for the operator diagnostic: a filing with 1500 segments and
  zero whitelisted sections produces a `section_classification_warnings`
  entry in the summary.

### Step 6 — Update the fragment + close the issue

Update `docs/known-issues/gh-612-...md`:

- Add a "Root cause (verified <date>)" section with the HTML markup
  findings.
- Add a "Fix" section describing the additive predicate.
- Add a "Verification" section listing the 6 filings + their
  post-fix detected sections.

On PR merge, the issue closes automatically via "Closes #612" in
the PR body.

## Constraints

- **Investigation precedes code.** Do not write the fix until you
  have written up the root cause with concrete HTML citations. The
  Datadog gh-574 fragment is a good model — it shows specific line
  numbers and snippets.

- **Additive only.** Long canonical headings must still match. The
  Datadog short-anchor-paragraph case (gh-574) must still match. Add
  tests for both as regression guards.

- **Tier-1 zero-tolerance gate must remain green.** Run
  `python3 -m src.gold_standard.v2_validator --fail-on-regression`
  before and after the fix. Both must exit 0. If the fix changes
  segment extraction broadly, this is the canary.

- **No edits to**: prompt YAMLs, threshold YAMLs, classifier client,
  Phase-1 / Phase-2 eval scripts (except the diagnostic warning in
  step 3). Stay in ingestion + section_classification + the tests.

- **No worker confidence in untested HTML variants.** If a filing
  uses a markup variant not seen in the 6 sample files, do not
  hypothetically extend the fix to cover it. Mark it as out of scope.

## Acceptance

- All 6 affected filings detect at least one whitelisted section
  (MDA, Business, or Risk Factors) post-fix.
- `pytest -x -q` green, including the new unit tests.
- Tier-1 zero-tolerance gate exits 0 before and after.
- gh-612 fragment updated with root-cause + fix + verification.
- Operator diagnostic surfaces the gap in `summary.json` (validated
  by running `--dry-run --gold-only` and checking the output).

## What NOT to do

- Don't speculatively expand `SECTION_PATTERNS` with regexes for
  markup variants you haven't observed in the 6 sample filings.
- Don't relax `_is_section_heading()` predicates broadly — match the
  evidence.
- Don't touch the classifier, prompts, or gate criteria.
- Don't widen the touched files beyond:
  - `src/extraction_v2/stages/ingestion.py` OR
    `src/extraction_v2/stages/section_classification.py` (whichever
    the fix lives in)
  - `tests/unit/extraction_v2/test_ingestion.py` OR
    `tests/unit/extraction_v2/test_section_classification.py`
  - `scripts/run_phase2_quantitative_eval.py` (just the diagnostic
    warning + summary field)
  - `docs/known-issues/gh-612-section-classification-variant-gap.md`
    (update with root cause + fix)

## Why this design

- **Investigation-first protects against bad fixes.** The gh-574
  fragment's "Root cause (verified)" section is the template — it
  surfaces a real markup pattern with concrete citations, then fixes
  exactly that. Anything looser risks dragging in TOC entries or
  footnote numbers as fake "headings."

- **The operator diagnostic is the highest long-term value.** Even
  after this fix, the next variant we haven't seen will eventually
  surface. Making it visible in `summary.json` means future
  operators don't waste $14 on a gate run before noticing 11% of
  their corpus had no paraphrase signal.

- **Six samples is enough scope to find a pattern but small enough
  to inspect manually.** Don't try to write a fix that covers every
  conceivable SEC filing — fix the observed variant.

## Parallel coordination

This worker can run in parallel with the **Phase-2 gate v2 worker**
(`PICK_phase2_gate_v2_c3_reframe_plus_fixes.md`). The two touch
different files entirely:

- Gate v2 → `scripts/run_phase2_quantitative_eval.py`
- This worker → `src/extraction_v2/stages/ingestion.py` (or
  section_classification) + tests + the warning hook in the eval
  script

If this worker lands before the gate v2 re-run, the v2 corpus picks
up ~11% more paraphrase coverage and is more likely to surface
classifier-only positives — strictly better signal. If it lands
after, no harm; just file as a follow-up and the next gate run
benefits.
