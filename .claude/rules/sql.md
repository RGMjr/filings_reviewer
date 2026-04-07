---
paths:
  - "sql/**"
---

# SQL Migration Rules

## Naming Convention
Files must be named `NN_description.sql` where `NN` is a zero-padded integer (e.g., `15_add_indexes.sql`).

## Ordering Requirements
- Numbers must be sequential with no gaps
- No duplicate numbers — each migration gets a unique number
- Check existing files before choosing a number: `ls sql/ | sort`

## FK Dependency Rules
- A migration may only reference tables defined in **earlier-numbered** migrations
- Never forward-reference a table that will be created in a later migration
- If two migrations are mutually dependent, combine them into one

## Registration Checklist
After creating a new migration file:
1. Confirm the number is unique and sequential
2. Verify all FK targets exist in lower-numbered files
3. Test locally before committing: `psql $DATABASE_URL -f sql/NN-description.sql`
4. If the migration adds tables or columns used by Python code, update `src/infra/db.py` in the same commit

## Known Numbering Issue
This project has duplicate numbers in the current `sql/` directory (e.g., two `04_`, two `08_`, two `09_`, etc.) from historical splits. New migrations must not add further duplicates — use the next unused number after the highest existing one.
