#!/usr/bin/env python3
"""One-off script to add duplicate_group column to gold standard CSV. Delete after use."""

import csv
import re
from pathlib import Path

CSV_PATH = Path(__file__).parent.parent / "data" / "gold_standard" / "golden_set_251218.csv"


def normalize_metric_id(raw_id: str) -> str:
    if not raw_id:
        return ""
    return raw_id.strip().lower()


def normalize_value(raw: str) -> float | None:
    if not raw or raw.strip().lower() in ('chart', 'n/a', '-', ''):
        return None
    cleaned = raw.strip()
    cleaned = re.sub(r'[$,]', '', cleaned)
    if '%' in cleaned:
        cleaned = cleaned.replace('%', '')
        try:
            return float(cleaned) / 100
        except ValueError:
            return None
    multipliers = {
        'trillion': 1_000_000_000_000,
        't': 1_000_000_000_000,
        'billion': 1_000_000_000,
        'b': 1_000_000_000,
        'million': 1_000_000,
        'm': 1_000_000,
        'thousand': 1_000,
        'k': 1_000,
    }
    pattern = r'([\d.]+)\s*(trillion|billion|million|thousand|t|b|m|k)?'
    match = re.search(pattern, cleaned, re.IGNORECASE)
    if match:
        try:
            num = float(match.group(1))
            mult_str = match.group(2)
            if mult_str:
                mult = multipliers.get(mult_str.lower(), 1)
                return num * mult
            return num
        except ValueError:
            pass
    try:
        return float(cleaned)
    except ValueError:
        return None


def main() -> None:
    with open(CSV_PATH, encoding='utf-8-sig', newline='') as f:
        reader = csv.DictReader(f)
        fieldnames = list(reader.fieldnames or [])
        rows = list(reader)

    # Build group key for each row
    def group_key(row: dict) -> tuple:
        company = row.get('Company', '')
        raw_metric = row.get('Standard Metric Name', '')
        new_metric = row.get('New standard metric?', '').strip()
        metric_id = normalize_metric_id(raw_metric)
        if not metric_id and new_metric and new_metric.lower().startswith('cm_'):
            metric_id = normalize_metric_id(new_metric)
        raw_value = row.get('Raw value', '')
        norm_val = normalize_value(raw_value)
        # Use normalized value if parseable, else raw stripped string
        val_key = norm_val if norm_val is not None else raw_value.strip().lower()
        return (company, metric_id, val_key)

    # Count occurrences per group key
    from collections import Counter, defaultdict
    key_counts: Counter = Counter(group_key(r) for r in rows)

    # Track group IDs for multi-row groups
    group_id_map: dict = {}
    group_counter = 0
    seen_keys: dict = defaultdict(int)

    # Add duplicate_group column
    new_fieldnames = fieldnames + ['duplicate_group']
    for row in rows:
        key = group_key(row)
        if key_counts[key] == 1:
            row['duplicate_group'] = ''
        else:
            if key not in group_id_map:
                group_counter += 1
                group_id_map[key] = f'G{group_counter:03d}'
            gid = group_id_map[key]
            count = seen_keys[key]
            row['duplicate_group'] = f'{gid}:primary' if count == 0 else f'{gid}:dup'
            seen_keys[key] += 1

    with open(CSV_PATH, 'w', encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=new_fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    multi = sum(1 for c in key_counts.values() if c > 1)
    print(f"Done. {len(rows)} rows, {group_counter} duplicate groups ({multi} distinct keys with duplicates).")


if __name__ == '__main__':
    main()
