# Manual Testing Guide

Quick guide for manually testing the V1 human review system (Flask app, port 5000).

> Note: `scripts/setup_manual_test.py` has been removed. Use the manual setup steps and database checks below. For the V2 review interface, see `docs/V2_HUMAN_REVIEW_GUIDE.md`.

## Quick Start

**Single command to set up everything:**

```bash
python3 scripts/setup_manual_test.py
```

This script will:
1. ✓ Check database connection
2. ✓ Verify review schema exists
3. ✓ Load Farfetch and Samsara test data
4. ✓ Generate source segments from HTML filings
5. ✓ Generate review candidates
6. ✓ Start Flask application on http://localhost:5000

## Prerequisites

**Database must be running:**
```bash
docker compose up -d
```

**Review schema must be created:**
```bash
PGPASSWORD=dev psql -h localhost -p 5433 -U dev -d filings_analysis < sql/07_create_review_schema.sql
```

## What to Test

### 1. Filing List Page
Navigate to: http://localhost:5000/review/filings

**Check:**
- [ ] Filings with candidates are displayed
- [ ] Company names show correctly
- [ ] Candidate count badges are accurate
- [ ] Pagination works (if >10 filings)
- [ ] Clicking a filing navigates to review page

**Screenshot locations for issues:**
- Save to: `screenshots/filing-list-[issue-name].png`

### 2. Review Page
Navigate to: http://localhost:5000/review/filings/[filing_id]

**Check:**
- [ ] Candidate details display correctly:
  - Number value and format
  - Metric keyword found
  - Context text (before/after)
- [ ] Accept button works
- [ ] Reject button works
- [ ] Metric dropdown populates
- [ ] Decision saves successfully
- [ ] Success message appears after saving
- [ ] Progress indicator updates
- [ ] Navigate to next/previous candidate
- [ ] "Back to filings" link works

**Screenshot locations for issues:**
- Save to: `screenshots/review-page-[issue-name].png`

### 3. API Endpoints (via Browser DevTools)

**Open DevTools (F12) → Network tab:**
- [ ] POST /api/decisions returns 201
- [ ] POST with invalid data returns 400
- [ ] POST with invalid candidate_id returns 404
- [ ] GET /api/filings/[id]/decisions returns decisions

**Save network logs for issues:**
- Right-click request → Copy → Copy as cURL
- Paste into issue report

## Reporting Issues

When you find an issue, provide:

### 1. Screenshot
- Save to `screenshots/` directory
- Name descriptively: `filing-list-pagination-broken.png`

### 2. Browser Console Output
```
F12 → Console tab → Copy all errors/warnings
```

### 3. Flask Server Logs
```
Copy the terminal output from the Flask server
Include the full stack trace if there's an error
```

### 4. Network Request (if API issue)
```bash
# Copy the failing request as cURL from DevTools
curl -X POST http://localhost:5000/api/decisions \
  -H "Content-Type: application/json" \
  -d '{"candidate_id": 123, ...}'
```

### 5. Database State (if data issue)
```bash
PGPASSWORD=dev psql -h localhost -p 5433 -U dev -d filings_analysis -c "
SELECT * FROM review.candidates WHERE candidate_id = 123;
"
```

### 6. Issue Template
```
**Issue:** [Brief description]

**Steps to reproduce:**
1. Navigate to [URL]
2. Click [button/link]
3. Observe [unexpected behavior]

**Expected:** [What should happen]

**Actual:** [What actually happened]

**Screenshots:** [Path to screenshot]

**Console errors:** [Copy from browser console]

**Server logs:** [Copy from Flask terminal]

**Database query:** [If relevant]
```

## Quick Database Checks

**Check candidates count:**
```bash
PGPASSWORD=dev psql -h localhost -p 5433 -U dev -d filings_analysis -c "
SELECT f.filing_id, c.company_name, COUNT(rc.candidate_id) as candidates
FROM filings f
JOIN companies c ON f.company_id = c.company_id
LEFT JOIN review.candidates rc ON f.filing_id = rc.filing_id
GROUP BY f.filing_id, c.company_name;"
```

**Check decisions count:**
```bash
PGPASSWORD=dev psql -h localhost -p 5433 -U dev -d filings_analysis -c "
SELECT decision, COUNT(*) FROM review.decisions GROUP BY decision;"
```

**View recent decisions:**
```bash
PGPASSWORD=dev psql -h localhost -p 5433 -U dev -d filings_analysis -c "
SELECT d.decision_id, d.candidate_id, d.decision, m.metric_name, d.created_at
FROM review.decisions d
LEFT JOIN metrics m ON d.metric_id = m.metric_id
ORDER BY d.created_at DESC
LIMIT 10;"
```

## Reset Test Data

**To start fresh:**
```bash
# Clear review data only
PGPASSWORD=dev psql -h localhost -p 5433 -U dev -d filings_analysis -c "
TRUNCATE review.decisions CASCADE;
TRUNCATE review.candidates CASCADE;"

# Clear everything and re-run setup
PGPASSWORD=dev psql -h localhost -p 5433 -U dev -d filings_analysis -c "
TRUNCATE companies CASCADE;"

python3 scripts/setup_manual_test.py
```

## Common Issues

### Issue: "Review schema not found"
```bash
PGPASSWORD=dev psql -h localhost -p 5433 -U dev -d filings_analysis < sql/07_create_review_schema.sql
```

### Issue: "No filing files found"
Check that filings exist in `data/filings/[CIK]/`

### Issue: Flask port already in use
```bash
# Find and kill process on port 5000
lsof -ti:5000 | xargs kill -9
```

### Issue: Database connection failed
```bash
# Check if PostgreSQL is running
docker compose ps

# Restart if needed
docker compose restart
```

## Stopping the Server

Press `Ctrl+C` in the terminal where Flask is running.

## Re-running Tests

Simply run the setup script again:
```bash
python3 scripts/setup_manual_test.py
```

The script is idempotent - it won't duplicate data if run multiple times.
