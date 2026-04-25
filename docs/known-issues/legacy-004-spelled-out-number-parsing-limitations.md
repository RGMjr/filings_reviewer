---
autonomy: n/a
discovered: '2026-04-22'
estimated: —
id: 4
note: Known limitation; not actionable
severity: low
slug: spelled-out-number-parsing-limitations
source: legacy
status: archived
title: Spelled-Out Number Parsing Limitations
touches: []
updated: '2026-04-24'
---

### Current Support

The system correctly parses:
- Simple numbers: "six", "twenty", "ninety"
- Teen numbers: "eleven", "fifteen", "nineteen"
- Compound numbers: "twenty-one", "forty-five"
- Magnitude words: "five million", "two billion"
- Hundreds: "hundred", "one hundred", "two hundred"

### Not Supported

Complex numbers like:
- "one hundred twenty-three" (compound hundreds)
- "two thousand five hundred" (multi-magnitude)
- "four hundred and fifty" (with "and")

### Rationale

These complex spelled-out numbers are rare in SEC filings - companies typically use numeric format for precision. The current implementation handles the common cases (e.g., "six months" for CAC payback period).
