# Admin Review Tool — Runbook

The admin review tool lives at `/admin/review`. It surfaces images and decisions that the normal reviewer queue hides, so an administrator can:

1. **Audit suppressed images** — those filtered by `LEARNED_TRIAGE_MIN`, the `decorative` / `logo` / `signature` classification block, the image-level `skipped` flag, or the "Reject all (no relevant metrics)" sentinel pattern.
2. **Audit reviewer decisions** — filter every `v2_image_metric_confirmations` row by reviewer to spot systematic errors, then reverse them with attribution.

All admin actions are logged to `admin_audit_log` and produce new rows in `v2_image_metric_confirmations` rather than mutating existing reviewer rows.

## Designating an admin

The page is gated by `auth_users.role = 'admin'` (hard-gated; unaffected by Stage B/C state). To grant a user admin access:

```bash
python3 scripts/seed_auth_users.py --email <user@example.com> --role admin
```

If the script does not accept `--role`, apply via SQL:

```sql
UPDATE auth_users
SET role = 'admin'
WHERE normalized_email = '<user@example.com>';
```

The user must subsequently log in via OAuth (`google_login_enabled` flag must be `true` in `feature_flags`) before the gate sees their role.

## Accessing the page

1. Sign in at the project's normal login URL.
2. Navigate to `/admin/review` (no nav link by design — admin only).
3. Non-admin users hitting the URL get `403 { "error": "admin access required" }`.

## Tab 1 — Suppressed Images

Filters by:
- **Suppression reason** (multi-select)
  - `skipped` — `review_status = 'skipped'`
  - `low_score` — `predicted_relevance < 0.230` (current Phase 1 threshold)
  - `hidden_classification` — `classification IN ('decorative', 'logo', 'signature')`
  - `sentinel_reject` — image has at least one `v2_image_metric_confirmations` row with `decision='reject'` and `rejection_reason='no_relevant_metrics'`
- **Score range**, **company substring**, **filing date range**

Each card surfaces an **Override** button. Clicking it opens the override modal, where you choose:
- An action (`add`, `accept`, or `reject`)
- A metric ID (datalist of Tier-1 metric IDs provided; any `cm_*` string accepted)
- A required override reason (≥5 characters)

Submitting writes:
- One row to `v2_image_metric_confirmations` with `override_reason` populated, `reviewer_id` = admin's user ID, `supersedes_confirmation_id` = NULL (since no prior reviewer decision is being reversed)
- A row to `admin_audit_log` with `action_type = 'image.admin_review_suppressed'`
- A promoted row in `v2_metric_facts` if the action was `accept`, `correct`, or `add` (existing chart-fact promotion logic fires)

## Tab 2 — Reviewer Audit

Enter a `reviewer_id` (UUID string from `auth_users.id`) — the page shows the ten most recently active reviewers as one-click links. Filter by decision type, date range, and whether existing admin overrides cover the row.

Each row shows:
- The reviewer's decision (metric, decision type, rejection reason)
- The image thumbnail and source company/filename
- Any existing admin override (with a one-click **undo** link)
- An **Override** button — opens the same modal as Tab 1, pre-filled with `supersedes_confirmation_id` set to the row being reversed

Submitting an override here writes:
- Same as Tab 1, but `supersedes_confirmation_id` points at the reviewer's row
- `admin_audit_log.action_type = 'image.admin_override_create'`
- Audit-log `before_state` JSONB captures a snapshot of the reviewer row being superseded
- The reviewer's original row is **kept** (not modified) — the admin's row coexists with it. The training pipeline sees both rows; the "any accept wins" aggregation in `scripts/export_image_training_data.py` means an admin accept overrides a reviewer reject at training-label level.

## Useful audit queries

**Recent admin actions:**

```sql
SELECT action_type, actor_email, target_entity,
       after_state->>'override_reason' AS reason,
       created_at
FROM admin_audit_log
WHERE action_type LIKE 'image.admin_%'
ORDER BY created_at DESC
LIMIT 50;
```

**All admin overrides on a given reviewer:**

```sql
SELECT a.created_at, a.override_reason,
       r.id AS reviewer_row_id, r.decision AS reviewer_decision,
       r.confirmed_metric_id, r.detected_metric_id
FROM v2_image_metric_confirmations a
JOIN v2_image_metric_confirmations r ON a.supersedes_confirmation_id = r.id
WHERE r.reviewer_id = '<reviewer-uuid>'
ORDER BY a.created_at DESC;
```

**Suppressed-image-with-admin-override (images where the admin disagreed with the suppression):**

```sql
SELECT ia.img_id, ia.filename, c.company_name,
       ia.predicted_relevance, ia.review_status,
       imc.override_reason
FROM v2_image_assets ia
JOIN v2_image_metric_confirmations imc ON imc.img_id = ia.img_id
JOIN filings f ON f.filing_id = ia.filing_id
JOIN companies c ON c.company_id = f.company_id
WHERE imc.override_reason IS NOT NULL
  AND imc.supersedes_confirmation_id IS NULL
ORDER BY imc.created_at DESC;
```

## Reversing an admin override

Each admin row carries a one-click **undo** affordance in the Reviewer Audit tab. The DELETE endpoint:

```
DELETE /api/admin/image-decision-override/<override_id>
```

This:
- Deletes the admin's confirmation row
- Calls `_demote_chart_fact_if_no_other_accepts` so any chart fact promoted by the admin's accept is rolled back when no other accepting confirmation remains
- Writes `admin_audit_log` with `action_type = 'image.admin_override_undo'`

The endpoint refuses to delete reviewer rows (returns 400 if `override_reason IS NULL` on the target row).

## Training signal interpretation

The trainer (`scripts/export_image_training_data.py`) does **not** consult the new `override_reason` or `supersedes_confirmation_id` columns. Admin overrides influence training only through the existing per-image label aggregation:

- "Any accept on an image" → image labeled **relevant** for training
- "All rejects on an image" → image labeled **not relevant**

An admin `accept` row coexisting with a reviewer `reject` row therefore flips the label to relevant. This is the desired behavior: admin disagreement with a reviewer rejection becomes a positive training signal. A future trainer iteration can weight admin rows differently using the new columns; that's out of scope for this rollout.

## Operational notes

- The `/admin/review` page does **not** appear in the main nav by design. Bookmark the URL.
- Multiple admins can override the same image; each gets their own row (unique key includes `reviewer_id`). The most recent admin row is shown on the audit tab.
- The same admin clicking "Override" twice on the same image with the same metric will UPSERT (replace) their own prior row — this is the existing `v2_image_metric_confirmations` unique-index behavior.
- The CHECK constraint on `v2_image_metric_confirmations` rejects any row with `supersedes_confirmation_id IS NOT NULL AND override_reason IS NULL`. Application logic already enforces this; the constraint is defense in depth.
