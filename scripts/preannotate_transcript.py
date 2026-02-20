#!/usr/bin/env python3
"""
LLM Pre-Annotation Script for Earnings Call Transcripts.

Sends a transcript to Claude (Anthropic API) with a definitions-based taxonomy
prompt and outputs a candidate annotation CSV for human review.

DESIGN PRINCIPLE: The prompt uses CONCEPTUAL DEFINITIONS of metrics, not regex
patterns from config/metric_keywords.yaml. This ensures the LLM's error profile
differs from the pipeline's keyword-matching approach, preventing circular evaluation.

The output CSV is sorted LOW → MEDIUM → HIGH confidence to force critical engagement
with uncertain annotations first. 2-3 synthetic "trap" annotations are injected to
detect rubber-stamping during human review.

Usage:
    # Annotate a single transcript
    python3 scripts/preannotate_transcript.py data/spike_samples/transcripts/CRM_2025-02-26.txt

    # Annotate with explicit metadata override
    python3 scripts/preannotate_transcript.py data/spike_samples/transcripts/CRM_2025-02-26.txt \\
        --company "Salesforce" --ticker CRM --date 2025-02-26

    # Annotate all transcripts in a directory
    python3 scripts/preannotate_transcript.py --all data/spike_samples/transcripts/

    # Use a specific model (default: claude-haiku-4-5-20251001)
    python3 scripts/preannotate_transcript.py transcript.txt --model claude-sonnet-4-6

    # Disable cache (force fresh LLM call)
    python3 scripts/preannotate_transcript.py transcript.txt --no-cache

Output:
    data/transcript_gold_standard/{TICKER}_{DATE}_preannotated.csv
"""

import argparse
import csv
import hashlib
import json
import logging
import os
import random
import re
import sqlite3
import sys
import textwrap
import threading
import time
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.gold_standard.transcript_metrics import ACTIVE_METRICS  # noqa: E402

logger = logging.getLogger("preannotate_transcript")

# Output directory
OUTPUT_DIR = ROOT / "data" / "transcript_gold_standard"

# Inventory CSV for company metadata lookup
INVENTORY_PATH = ROOT / "data" / "spike_samples" / "inventory.csv"

# Taxonomy YAML path
TAXONOMY_PATH = ROOT / "config" / "transcript_annotation_taxonomy.yaml"

# Cache database
CACHE_PATH = ROOT / "data" / "annotation_cache.db"

# Model to use (haiku for cost; override with --model for higher quality)
DEFAULT_MODEL = "claude-haiku-4-5-20251001"

# Confidence ordering for sort (LOW first to force critical engagement)
CONFIDENCE_ORDER = {"LOW": 0, "MEDIUM": 1, "HIGH": 2}

# Synthetic trap annotations — plausible-sounding but NOT customer metrics.
# Reviewer must REJECT these. Randomly sample 2-3 per transcript.
TRAP_TEMPLATES = [
    {
        "metric_id": "cm_arr",  # Trap: This is actually total GAAP revenue, not ARR
        "value": "{revenue_value}",
        "unit": "currency",
        "period": "{period}",
        "source_type": "text",
        "raw_text": "Total revenue for the {period} was ${revenue_value_b} billion",
        "confidence": "HIGH",
        "section": "prepared_remarks",
        "is_trap": "true",
        "_trap_reason": "GAAP revenue stated as ARR — should be REJECTED (not recurring revenue)",
    },
    {
        "metric_id": "cm_new_customers_acquired",
        "value": "{headcount}",
        "unit": "count",
        "period": "{period}",
        "source_type": "text",
        "raw_text": "We ended {period} with {headcount} employees globally",
        "confidence": "MEDIUM",
        "section": "prepared_remarks",
        "is_trap": "true",
        "_trap_reason": "Employee headcount stated as new customer acquisitions — REJECT",
    },
    {
        "metric_id": "cm_customers_period_end",
        "value": "{partner_count}",
        "unit": "count",
        "period": "{period}",
        "source_type": "text",
        "raw_text": "Our partner ecosystem now includes {partner_count} certified partners",
        "confidence": "MEDIUM",
        "section": "q_and_a",
        "is_trap": "true",
        "_trap_reason": "Partner count stated as paying customers — REJECT",
    },
    {
        "metric_id": "cm_net_revenue_retention",
        "value": "0.92",
        "unit": "percent",
        "period": "{period}",
        "source_type": "text",
        "raw_text": "Our gross margin improved to 92% this quarter",
        "confidence": "MEDIUM",
        "section": "prepared_remarks",
        "is_trap": "true",
        "_trap_reason": "Gross margin stated as NRR — REJECT",
    },
    {
        "metric_id": "cm_revenue_per_customer",
        "value": "{stock_price}",
        "unit": "currency",
        "period": "{period}",
        "source_type": "text",
        "raw_text": "Our stock has appreciated to approximately ${stock_price} per share",
        "confidence": "LOW",
        "section": "q_and_a",
        "is_trap": "true",
        "_trap_reason": "Stock price stated as revenue per customer — REJECT",
    },
]


# ---------------------------------------------------------------------------
# Simple SQLite cache for LLM responses
# ---------------------------------------------------------------------------


class _AnnotationCache:
    """Thread-safe SQLite cache for LLM annotation responses."""

    CACHE_VERSION = "annotation-v1"

    def __init__(self, db_path: Path):
        self._db_path = db_path
        self._lock = threading.Lock()
        self._conn: sqlite3.Connection | None = None
        self._init_db()

    def _init_db(self) -> None:
        db_path = self._db_path
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False, timeout=10.0)
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS annotation_cache (
                cache_key TEXT PRIMARY KEY,
                cache_version TEXT NOT NULL,
                model TEXT NOT NULL,
                response_content TEXT NOT NULL,
                input_tokens INTEGER NOT NULL,
                output_tokens INTEGER NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """
        )
        self._conn.commit()

    def _key(self, model: str, system: str, user: str) -> str:
        data = json.dumps({"model": model, "system": system, "user": user}, sort_keys=True)
        return hashlib.sha256(data.encode()).hexdigest()

    def get(self, model: str, system: str, user: str) -> str | None:
        if not self._conn:
            return None
        key = self._key(model, system, user)
        with self._lock:
            row = self._conn.execute(
                "SELECT response_content FROM annotation_cache "
                "WHERE cache_key = ? AND cache_version = ? "
                "AND created_at > datetime('now', '-30 days')",
                (key, self.CACHE_VERSION),
            ).fetchone()
        return row[0] if row else None

    def set(
        self,
        model: str,
        system: str,
        user: str,
        content: str,
        input_tokens: int,
        output_tokens: int,
    ) -> None:
        if not self._conn:
            return
        key = self._key(model, system, user)
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO annotation_cache "
                "(cache_key, cache_version, model, response_content, input_tokens, output_tokens) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (key, self.CACHE_VERSION, model, content, input_tokens, output_tokens),
            )
            self._conn.commit()


# ---------------------------------------------------------------------------
# Taxonomy loading
# ---------------------------------------------------------------------------


def load_taxonomy(path: Path) -> dict:
    """Load metric taxonomy from YAML."""
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def build_system_prompt(taxonomy: dict, company: str, ticker: str) -> str:
    """
    Build the LLM system prompt from taxonomy definitions.

    Uses CONCEPTUAL DEFINITIONS only — no regex patterns — so the LLM's
    error profile differs from the pipeline's keyword-matching approach.
    """
    metrics = taxonomy.get("metrics", {})
    rules = taxonomy.get("annotation_rules", {})

    lines = [
        "You are an expert financial data annotator specializing in customer metrics "
        "from earnings call transcripts.",
        "",
        f"Company: {company} (ticker: {ticker})",
        "",
        "Your task: Identify ALL mentions of the following customer metrics in the transcript.",
        "Return a JSON array — one object per distinct metric mention.",
        "",
        "## METRIC TAXONOMY",
        "",
        "For each metric below, I describe what it IS and what it is NOT.",
        "Use these DEFINITIONS to identify metrics — not keywords or patterns.",
        "",
    ]

    for metric_id, meta in sorted(metrics.items()):
        label = meta.get("label", metric_id)
        definition = meta.get("definition", "").strip()
        examples = meta.get("examples", [])
        not_this = meta.get("not_this", [])
        notes = meta.get("notes", "").strip()

        lines.append(f"### {metric_id}")
        lines.append(f"**{label}**")
        lines.append(f"{definition}")
        if examples:
            lines.append("Examples:")
            for ex in examples[:3]:
                lines.append(f'  - "{ex}"')
        if not_this:
            lines.append("Do NOT annotate as this metric:")
            for nt in not_this[:2]:
                lines.append(f"  - {nt}")
        if notes:
            lines.append(f"Note: {notes}")
        lines.append("")

    lines.extend(
        [
            "## ANNOTATION RULES",
            "",
        ]
    )

    # Flatten annotation rules into readable text
    for rule_key, rule_val in rules.items():
        if isinstance(rule_val, str):
            lines.append(f"**{rule_key}**: {rule_val.strip()}")
            lines.append("")
        elif isinstance(rule_val, dict):
            lines.append(f"**{rule_key}**:")
            for sub_key, sub_val in rule_val.items():
                if isinstance(sub_val, str):
                    lines.append(f"  - {sub_key}: {sub_val.strip()}")
            lines.append("")

    lines.extend(
        [
            "## OUTPUT FORMAT",
            "",
            "Return a JSON array (and ONLY the JSON — no other text).",
            "Each element must have these exact fields:",
            "",
            "```json",
            "[",
            "  {",
            '    "metric_id": "cm_arr",',
            '    "value": "1200000000",',
            '    "unit": "currency",',
            '    "period": "Q4 FY2025",',
            '    "source_type": "text",',
            '    "raw_text": "the exact sentence(s) containing the metric",',
            '    "confidence": "HIGH",',
            '    "section": "prepared_remarks"',
            "  }",
            "]",
            "```",
            "",
            "Field rules:",
            "- metric_id: Must be one of the cm_* IDs listed above",
            '- value: Numeric string (e.g. "1200000000"), or "" if only a growth rate is stated',
            '- unit: "currency", "count", "percent", or "ratio"',
            '- period: Fiscal period (e.g. "Q4 FY2025", "FY2024", "Q1 2025")',
            '- source_type: Always "text" for transcripts',
            "- raw_text: 1-2 sentences verbatim from the transcript (max 200 chars)",
            '- confidence: "HIGH", "MEDIUM", or "LOW" per the confidence guidance above',
            '- section: "prepared_remarks", "q_and_a", or "analyst"',
            "",
            "Important:",
            "- Include ALL metric mentions, even if the same metric appears multiple times",
            "- Do NOT include analyst estimates, guidance, or forward-looking statements",
            '- If a metric is mentioned but no number is given, include it with value = ""',
            "- Return [] if no customer metrics are found",
        ]
    )

    return "\n".join(lines)


def build_user_prompt(
    transcript_text: str,
    company: str,
    ticker: str,
    date: str,
    fiscal_year_end: str = "December",
    quarter: str = "",
) -> str:
    """Build the user turn prompt with transcript content and metadata."""
    header = textwrap.dedent(
        f"""
        Transcript metadata:
        - Company: {company}
        - Ticker: {ticker}
        - Date: {date}
        - Quarter: {quarter}
        - Fiscal year end: {fiscal_year_end}

        Identify all customer metric mentions in the following transcript.
        Remember: ONLY annotate the {len(ACTIVE_METRICS)} active cm_* metrics listed in your instructions.

        === TRANSCRIPT START ===
    """
    ).strip()

    # Truncate very long transcripts to avoid token limits (keep ~120K chars)
    max_chars = 120_000
    if len(transcript_text) > max_chars:
        transcript_text = transcript_text[:max_chars] + "\n\n[TRANSCRIPT TRUNCATED]"
        logger.warning("Transcript truncated to %d chars", max_chars)

    return f"{header}\n\n{transcript_text}\n\n=== TRANSCRIPT END ==="


# ---------------------------------------------------------------------------
# Anthropic API call
# ---------------------------------------------------------------------------


def call_anthropic(
    system: str,
    user: str,
    model: str,
    cache: _AnnotationCache | None,
    max_retries: int = 3,
) -> tuple[str, int, int]:
    """
    Call Anthropic API with retry logic and caching.

    Returns: (response_content, input_tokens, output_tokens)
    """
    try:
        import anthropic
    except ImportError as err:
        raise ImportError("anthropic package not installed. Run: uv pip install anthropic") from err

    # Check cache first
    if cache:
        cached = cache.get(model, system, user)
        if cached:
            logger.info("Cache hit — skipping API call")
            return cached, 0, 0

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise ValueError(
            "ANTHROPIC_API_KEY environment variable not set. "
            "Export it before running: export ANTHROPIC_API_KEY=sk-ant-..."
        )

    client = anthropic.Anthropic(api_key=api_key)

    last_error: Exception | None = None
    for attempt in range(max_retries):
        try:
            response = client.messages.create(
                model=model,
                max_tokens=4096,
                temperature=0.1,
                system=system,
                messages=[{"role": "user", "content": user}],
            )
            content = response.content[0].text
            input_tokens = response.usage.input_tokens
            output_tokens = response.usage.output_tokens

            if cache:
                cache.set(model, system, user, content, input_tokens, output_tokens)

            logger.info(
                "API call complete: %d input + %d output tokens",
                input_tokens,
                output_tokens,
            )
            return content, input_tokens, output_tokens

        except Exception as e:
            last_error = e
            wait = 2**attempt
            logger.warning(
                "API call failed (attempt %d/%d): %s — retrying in %ds",
                attempt + 1,
                max_retries,
                e,
                wait,
            )
            time.sleep(wait)

    raise RuntimeError(f"Anthropic API failed after {max_retries} attempts: {last_error}")


# ---------------------------------------------------------------------------
# Response parsing
# ---------------------------------------------------------------------------


def parse_llm_response(raw: str, ticker: str, date: str, company: str) -> list[dict]:
    """
    Parse LLM JSON response into annotation rows.

    Handles common LLM formatting issues (markdown fences, leading text).
    Filters to valid metric IDs only.
    """
    # Strip markdown code fences if present
    text = raw.strip()
    text = re.sub(r"```(?:json)?\s*", "", text)
    text = re.sub(r"```\s*$", "", text)
    text = text.strip()

    # Find the JSON array
    start = text.find("[")
    end = text.rfind("]")
    if start == -1 or end == -1:
        logger.warning("No JSON array found in LLM response")
        return []

    json_text = text[start : end + 1]

    try:
        raw_annotations = json.loads(json_text)
    except json.JSONDecodeError as e:
        logger.error("Failed to parse LLM JSON: %s\nRaw (first 500): %s", e, json_text[:500])
        return []

    annotations = []
    seen: set[tuple] = set()

    for item in raw_annotations:
        if not isinstance(item, dict):
            continue

        metric_id = item.get("metric_id", "").strip()
        if metric_id not in ACTIVE_METRICS:
            logger.debug("Skipping unknown metric_id: %s", metric_id)
            continue

        value = str(item.get("value", "")).strip()
        unit = item.get("unit", "").strip()
        period = item.get("period", "").strip()
        raw_text = item.get("raw_text", "").strip()[:300]  # cap raw_text length
        confidence = item.get("confidence", "MEDIUM").strip().upper()
        section = item.get("section", "prepared_remarks").strip()
        source_type = item.get("source_type", "text").strip()

        # Normalize confidence
        if confidence not in CONFIDENCE_ORDER:
            confidence = "MEDIUM"

        # Deduplicate exact same metric+value+period
        dedup_key = (metric_id, value, period)
        if dedup_key in seen:
            logger.debug("Deduplicated: %s %s %s", metric_id, value, period)
            continue
        seen.add(dedup_key)

        annotations.append(
            {
                "company": company,
                "ticker": ticker,
                "date": date,
                "metric_id": metric_id,
                "value": value,
                "unit": unit,
                "period": period,
                "source_type": source_type,
                "raw_text": raw_text,
                "confidence": confidence,
                "section": section,
                "is_trap": "false",
            }
        )

    return annotations


# ---------------------------------------------------------------------------
# Trap injection
# ---------------------------------------------------------------------------


def inject_traps(
    annotations: list[dict],
    ticker: str,
    date: str,
    company: str,
    period: str,
    n_traps: int = 2,
) -> list[dict]:
    """
    Inject n_traps synthetic false positive annotations.

    Traps are plausible-looking but clearly wrong (employee count as customers,
    gross margin as NRR, stock price as ARPU, etc.). Reviewer must REJECT them.
    """
    traps = random.sample(TRAP_TEMPLATES, min(n_traps, len(TRAP_TEMPLATES)))

    # Generate plausible placeholder values
    replacements = {
        "{period}": period,
        "{revenue_value}": str(random.randint(1, 9) * 1_000_000_000),
        "{revenue_value_b}": str(random.randint(1, 9)),
        "{headcount}": str(random.randint(5000, 80000)),
        "{partner_count}": str(random.randint(200, 5000)),
        "{stock_price}": str(random.randint(50, 500)),
    }

    result = list(annotations)
    for trap_template in traps:
        trap = {
            "company": company,
            "ticker": ticker,
            "date": date,
            "is_trap": "true",
        }
        for field, template_val in trap_template.items():
            if field.startswith("_"):
                continue  # skip internal meta-fields
            val = str(template_val)
            for placeholder, replacement in replacements.items():
                val = val.replace(placeholder, replacement)
            trap[field] = val

        result.append(trap)

    return result


# ---------------------------------------------------------------------------
# Metadata lookup
# ---------------------------------------------------------------------------


def load_inventory(path: Path) -> dict[str, dict]:
    """Load inventory.csv into a dict keyed by TICKER_DATE."""
    inventory: dict[str, dict] = {}
    if not path.exists():
        return inventory
    with open(path, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            key = f"{row['ticker']}_{row['date']}"
            inventory[key] = row
    return inventory


def parse_filename_metadata(path: Path) -> tuple[str, str]:
    """
    Extract (ticker, date) from a filename like CRM_2025-02-26.txt or
    TMUS_2025-01-29.txt. Returns empty strings on failure.
    """
    stem = path.stem
    # Handle extra suffixes like CRM_2019-12-03_17_00_00
    match = re.match(r"^([A-Z]+)_(\d{4}-\d{2}-\d{2})", stem)
    if match:
        return match.group(1), match.group(2)
    return "", ""


# ---------------------------------------------------------------------------
# Main annotation logic
# ---------------------------------------------------------------------------


def annotate_transcript(
    transcript_path: Path,
    taxonomy: dict,
    inventory: dict[str, dict],
    model: str,
    cache: _AnnotationCache | None,
    company_override: str | None = None,
    ticker_override: str | None = None,
    date_override: str | None = None,
    n_traps: int = 2,
) -> Path:
    """
    Pre-annotate a single transcript file and write candidate CSV.

    Returns path to the output CSV.
    """
    ticker, date = parse_filename_metadata(transcript_path)
    if ticker_override:
        ticker = ticker_override
    if date_override:
        date = date_override

    # Look up company metadata
    inv_key = f"{ticker}_{date}"
    inv_entry = inventory.get(inv_key, {})
    company = company_override or inv_entry.get("company") or ticker
    quarter = inv_entry.get("quarter", "")
    fiscal_year_end = inv_entry.get("fiscal_year_end", "December")

    print(f"\n{'='*60}")
    print(f"  Annotating: {company} ({ticker}) — {date}")
    if quarter:
        print(f"  Quarter:    {quarter}")
    print(f"  Model:      {model}")
    print(f"{'='*60}")

    # Read transcript
    transcript_text = transcript_path.read_text(encoding="utf-8")
    print(f"  Transcript length: {len(transcript_text):,} chars")

    # Build prompts
    system_prompt = build_system_prompt(taxonomy, company, ticker)
    user_prompt = build_user_prompt(
        transcript_text, company, ticker, date, fiscal_year_end=fiscal_year_end, quarter=quarter
    )

    # Call LLM
    print("  Calling LLM...", end="", flush=True)
    t0 = time.time()
    raw_response, input_tokens, output_tokens = call_anthropic(
        system=system_prompt,
        user=user_prompt,
        model=model,
        cache=cache,
    )
    elapsed = time.time() - t0
    cached_marker = " (cached)" if input_tokens == 0 else ""
    print(f" done in {elapsed:.1f}s{cached_marker}")
    if input_tokens > 0:
        print(f"  Tokens: {input_tokens:,} in + {output_tokens:,} out")

    # Parse response
    annotations = parse_llm_response(raw_response, ticker, date, company)
    print(f"  Parsed {len(annotations)} candidate annotations")

    # Inject traps
    period = quarter or date
    annotations = inject_traps(annotations, ticker, date, company, period, n_traps=n_traps)
    trap_count = sum(1 for a in annotations if a.get("is_trap") == "true")
    print(f"  Injected {trap_count} trap annotations")

    # Sort: LOW first (forces critical engagement), then MEDIUM, then HIGH
    annotations.sort(key=lambda a: CONFIDENCE_ORDER.get(a.get("confidence", "MEDIUM"), 1))

    # Write output CSV
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUTPUT_DIR / f"{ticker}_{date}_preannotated.csv"

    fieldnames = [
        "company",
        "ticker",
        "date",
        "metric_id",
        "value",
        "unit",
        "period",
        "source_type",
        "raw_text",
        "confidence",
        "section",
        "is_trap",
    ]

    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(annotations)

    total = len(annotations)
    real = total - trap_count
    print(f"  Output: {out_path} ({real} candidates + {trap_count} traps)")
    return out_path


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(
        description="LLM pre-annotation for earnings call transcripts.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent(
            """
            Examples:
              %(prog)s data/spike_samples/transcripts/CRM_2025-02-26.txt
              %(prog)s --all data/spike_samples/transcripts/
              %(prog)s transcript.txt --model claude-sonnet-4-6 --no-cache
        """
        ),
    )
    parser.add_argument(
        "transcript",
        nargs="?",
        type=Path,
        help="Path to transcript .txt file",
    )
    parser.add_argument(
        "--all",
        type=Path,
        metavar="DIR",
        help="Annotate all .txt files in this directory",
    )
    parser.add_argument("--company", help="Company name override")
    parser.add_argument("--ticker", help="Ticker symbol override")
    parser.add_argument("--date", help="Date override (YYYY-MM-DD)")
    parser.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        help=f"Anthropic model (default: {DEFAULT_MODEL})",
    )
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="Disable response caching",
    )
    parser.add_argument(
        "--traps",
        type=int,
        default=2,
        metavar="N",
        help="Number of trap annotations to inject (default: 2)",
    )
    parser.add_argument(
        "--taxonomy",
        type=Path,
        default=TAXONOMY_PATH,
        help="Path to taxonomy YAML",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable verbose logging",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    if not args.transcript and not args.all:
        parser.error("Provide a transcript file or --all <directory>")

    # Load taxonomy
    if not args.taxonomy.exists():
        print(f"ERROR: Taxonomy file not found: {args.taxonomy}", file=sys.stderr)
        sys.exit(1)
    taxonomy = load_taxonomy(args.taxonomy)
    print(f"Loaded taxonomy: {len(taxonomy.get('metrics', {}))} metric definitions")

    # Load inventory
    inventory = load_inventory(INVENTORY_PATH)

    # Set up cache
    cache: _AnnotationCache | None = None
    if not args.no_cache:
        cache = _AnnotationCache(CACHE_PATH)

    # Collect files to process
    if args.all:
        transcript_files = sorted(args.all.glob("*.txt"))
        if not transcript_files:
            print(f"No .txt files found in {args.all}", file=sys.stderr)
            sys.exit(1)
        print(f"Found {len(transcript_files)} transcripts to annotate")
    else:
        if not args.transcript.exists():
            print(f"ERROR: File not found: {args.transcript}", file=sys.stderr)
            sys.exit(1)
        transcript_files = [args.transcript]

    # Run annotation
    output_paths = []
    errors = []
    for path in transcript_files:
        try:
            out = annotate_transcript(
                transcript_path=path,
                taxonomy=taxonomy,
                inventory=inventory,
                model=args.model,
                cache=cache,
                company_override=args.company if len(transcript_files) == 1 else None,
                ticker_override=args.ticker if len(transcript_files) == 1 else None,
                date_override=args.date if len(transcript_files) == 1 else None,
                n_traps=args.traps,
            )
            output_paths.append(out)
        except Exception as e:
            logger.error("Failed to annotate %s: %s", path.name, e)
            errors.append((path.name, str(e)))

    # Summary
    print(f"\n{'='*60}")
    print("  SUMMARY")
    print(f"  Annotated: {len(output_paths)}/{len(transcript_files)} transcripts")
    if errors:
        print(f"  Errors ({len(errors)}):")
        for name, err in errors:
            print(f"    {name}: {err}")
    print(f"  Output directory: {OUTPUT_DIR}")
    print(f"{'='*60}")

    if errors:
        sys.exit(1)


if __name__ == "__main__":
    main()
