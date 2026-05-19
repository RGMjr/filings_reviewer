---
id: 646
source: gh
slug: ar-revenue-cross-clause-disambiguation
title: AR-vs-revenue cross-clause disambiguation in cm_revenue_concentration
status: open
severity: medium
autonomy: skip
estimated: —
touches:
  - src/extraction_v2/stages/candidate_generation.py
  - config/metric_keywords.yaml
discovered: '2026-05-19'
updated: '2026-05-19'
gh_issue: 646
note: 50-char exclusion window misses cross-clause AR mentions; naive full-segment scan regresses Tier-1 GS — needs narrower mitigation
---

### Problem

The keyword-exclusion path for `cm_revenue_concentration` runs against a ±50 character window around the matched keyword (`src/extraction_v2/stages/candidate_generation.py::_is_excluded`). Two residual failure modes survive the parent fix that broadened the AR-exclusion regex:

**(a) Cross-clause AR mentions outside the 50-char window.** Example: "Our largest customer's total balance, accumulated over the prior fiscal year, made up 82% of accounts receivable" — the AR phrase is the clear referent of the value but sits >50 chars from the trigger keyword, so the exclusion does not fire. A naive widening to full-segment scan was attempted in the parent session and reverted because it caused a Tier-1 gold-standard presence-recall regression on Datadog, Samsara, and Tenable (over-excluded legitimate revenue-concentration sentences that also mention AR elsewhere in the segment).

**(b) Genuinely ambiguous "X% of revenue or accounts receivable" disclosures.** The value applies to both denominators by construction; treat as residual accepted-FP.

### Next Steps

- Pilot a narrower mitigation: forward-only window after the value, or 100–150 char window scoped to `cm_revenue_concentration` — verify against gold-standard before shipping.
- If neither variant is GS-safe, consider a positive-context guard at the FP-filter layer (`_rule_accounts_receivable`) that uses surrounding phrase polarity to choose between AR and revenue interpretations.
- Leave (b) as accepted residual unless it shows up in a future text-pattern analysis as a high-volume reject phrase.
