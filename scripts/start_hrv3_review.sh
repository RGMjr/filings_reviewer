#!/bin/bash
# HRV-3 Quick Start Script
# Starts the web review interface for Slack filing validation

set -e

echo "════════════════════════════════════════════════════════════════════════════════"
echo "  HRV-3: Slack Filing Review - Quick Start"
echo "════════════════════════════════════════════════════════════════════════════════"
echo ""
echo "Filing:        Slack Technologies, Inc. S-1 (filing_id=35)"
echo "Candidates:    111 review candidates"
echo "Gold Standard: 41 metrics in golden_set_251218.csv"
echo "Expected Time: 2-3 hours"
echo ""
echo "Reference Docs:"
echo "  - Review Guide:      docs/analysis/HRV-3_REVIEW_GUIDE.md"
echo "  - Validation Report: docs/analysis/HRV-3_SLACK_VALIDATION.md"
echo ""
echo "════════════════════════════════════════════════════════════════════════════════"
echo ""

# Check database is running
echo "✓ Checking database connection..."
if ! PGPASSWORD=dev psql -h localhost -p 5433 -U dev -d filings_analysis -c "SELECT 1" >/dev/null 2>&1; then
    echo "✗ ERROR: Database not accessible"
    echo "  Please start database: docker compose up -d"
    exit 1
fi
echo "✓ Database connected"
echo ""

# Verify candidates exist
CANDIDATE_COUNT=$(PGPASSWORD=dev psql -h localhost -p 5433 -U dev -d filings_analysis -t -c "SELECT COUNT(*) FROM review_candidates WHERE filing_id = 35" | xargs)
echo "✓ Found $CANDIDATE_COUNT review candidates for Slack filing"
echo ""

# Check review progress
REVIEWED=$(PGPASSWORD=dev psql -h localhost -p 5433 -U dev -d filings_analysis -t -c "SELECT COUNT(rd.decision_id) FROM review_candidates rc LEFT JOIN review_decisions rd ON rc.candidate_id = rd.candidate_id WHERE rc.filing_id = 35" | xargs)
PENDING=$((CANDIDATE_COUNT - REVIEWED))
echo "Review Progress:"
echo "  Reviewed: $REVIEWED / $CANDIDATE_COUNT"
echo "  Pending:  $PENDING"
echo ""

if [ $PENDING -eq 0 ]; then
    echo "════════════════════════════════════════════════════════════════════════════════"
    echo "  ✓ All candidates reviewed! Ready for validation."
    echo "════════════════════════════════════════════════════════════════════════════════"
    echo ""
    echo "Next step: Run validation script"
    echo ""
    echo "  DATABASE_URL=\"postgresql://dev:dev@localhost:5433/filings_analysis\" \\"
    echo "    python3 scripts/validate_against_gold_standard.py --filing-id 35 --verbose"
    echo ""
    exit 0
fi

echo "════════════════════════════════════════════════════════════════════════════════"
echo "  Starting Web Review Interface..."
echo "════════════════════════════════════════════════════════════════════════════════"
echo ""
echo "Once started:"
echo "  1. Open browser to http://localhost:8000"
echo "  2. Navigate to 'Slack Technologies, Inc.' filing"
echo "  3. Review each candidate (Accept/Reject)"
echo "  4. Document patterns as you go"
echo ""
echo "Press Ctrl+C to stop the server when done"
echo ""
echo "════════════════════════════════════════════════════════════════════════════════"
echo ""

# Start the web interface
cd "$(dirname "$0")/.."
export DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis"
python3 -m src.web.app
