---
autonomy: skip
discovered: '2026-04-22'
estimated: —
id: 5
note: Working as designed
severity: n/a
slug: revenue-synonym-context-gating
source: legacy
status: archived
title: Revenue Synonym Context Gating
touches: []
updated: '2026-04-24'
---

### Background

Revenue-related metrics (GMV, TCV, ACV, Bookings, Billings) only generate review candidates when cohort/per-customer context is present. This is intentional to reduce false positives.

### Current Behavior

- ARR/MRR: Always generate candidates (inherently customer-related)
- GMV/TCV/ACV/Bookings/Billings: Require context keywords within 1500 chars
- Context keywords: cohort, vintage, per customer, per user, by account, etc.

### Potential Issue

Some valid per-customer GMV values may not have context keywords nearby, causing them to be missed.

### Monitoring

Review rejection rates for revenue synonyms to determine if context gating is too strict.
