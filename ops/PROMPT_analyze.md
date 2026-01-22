# Ralph Analysis Loop - Regression Investigation

You are Claude, operating in a Ralph autonomous loop to investigate the Slack Technologies validation regression.

## Context

**Problem**: Validation shows P=28.6% R=63.6% F1=39.4% (baseline was P=76% R=84% F1=80%)
**Root causes identified**:
1. `cm_billings` generating 49 false positive candidates
2. Some candidates exist but aren't matching gold standard entries
3. Missing table values for `cm_large_customers_period_end`

## Your Task

1. Read `ops/ANALYSIS_PLAN.md` to find the next `[ ]` pending task
2. Execute the analysis for that ONE task only
3. Write findings to `ops/ANALYSIS_RESULTS.md`
4. Mark the task `[x]` complete in the plan
5. Commit changes with message: `analyze: TASK-N - brief summary`
6. Exit this session

## Analysis Commands

### For TASK-1 (cm_billings FP):
```bash
# Check keyword patterns for cm_billings
grep -A 20 "cm_billings:" config/metric_keywords.yaml

# See sample cm_billings candidates
python3 << 'EOF'
import sys
sys.path.insert(0, '.')
from src.gold_standard.fresh_extractor import extract_fresh
from pathlib import Path

result = extract_fresh(
    document_url='https://www.sec.gov/Archives/edgar/data/1764925/000162828019007428/slacks-1a3.htm',
    base_dir=Path('data/filings'),
    allow_sec_fetch=False
)

billings = [c for c in result.candidates if c.suggested_metric_id == 'cm_billings']
print(f'Total cm_billings candidates: {len(billings)}')
for c in billings[:15]:
    print(f'  {repr(c.raw_number_text)} keyword={repr(c.triggering_keyword)}')
    print(f'    context: ...{c.context_text[max(0,len(c.context_text)//2-50):len(c.context_text)//2+50]}...')
EOF
```

### For TASK-4 (575/645 matching debug):
```bash
# Check gold standard entries for these values
grep "575\|645" data/gold_standard/golden_set_251218.csv | grep -i slack

# Check candidate details
python3 << 'EOF'
import sys
sys.path.insert(0, '.')
from src.gold_standard.fresh_extractor import extract_fresh
from pathlib import Path

result = extract_fresh(
    document_url='https://www.sec.gov/Archives/edgar/data/1764925/000162828019007428/slacks-1a3.htm',
    base_dir=Path('data/filings'),
    allow_sec_fetch=False
)

for c in result.candidates:
    if c.suggested_metric_id == 'cm_large_customers_period_end':
        print(f'Candidate: {c.raw_number_text} parsed={c.parsed_value}')
        print(f'  keyword: {c.triggering_keyword}')
        print(f'  metric_id: {c.suggested_metric_id}')
        print()
EOF
```

### For TASK-5 (missing table values):
```bash
# Search for the table with Paid Customers >$100,000 values
grep -A 50 "Paid Customers" data/filings/0001764925/000162828019007428/slacks-1a3.htm | head -100
```

## File Locations

- Plan: `ops/ANALYSIS_PLAN.md`
- Results: `ops/ANALYSIS_RESULTS.md`
- Keyword config: `config/metric_keywords.yaml`
- Gold standard: `data/gold_standard/golden_set_251218.csv`
- Slack filing: `data/filings/0001764925/000162828019007428/slacks-1a3.htm`
- Validation script: `scripts/validate_against_gold_standard.py`

## Completion

After analysis and commit:
```
<promise>ANALYSIS_ITERATION_COMPLETE</promise>
```

If all tasks done:
```
<promise>ANALYSIS_COMPLETE</promise>
```
