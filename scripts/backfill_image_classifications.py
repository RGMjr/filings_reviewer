#!/usr/bin/env python3
"""Backfill v2_image_classifications for reviewed images not yet run through the Vision metric
classifier.

Selects images that:
- Have at least one v2_image_metric_confirmations row (reviewer ground truth exists)
- Have classification IN ('chart', 'table_image') on v2_image_assets
- Have a non-NULL file_path (image bytes accessible from storage)
- Do NOT already have a non-empty predicted_metrics row in v2_image_classifications

Ordering: images with the fewest confirmations are processed first so the
eval corpus has evenly distributed coverage rather than dense coverage on
a handful of heavily-reviewed images.

Cost estimate: ~$0.0005/call (rough order-of-magnitude for gemini-2.5-flash-lite;
actual cost depends on image size and prompt token count — verify against
billing after a test batch).

Usage::

    # Dry-run: count eligible images, estimate cost (no API calls, no writes)
    python3 scripts/backfill_image_classifications.py --dry-run

    # Classify up to 50 images, abort if spend exceeds $1.00
    python3 scripts/backfill_image_classifications.py --limit 50 --max-spend-usd 1.00

    # Override provider/model
    python3 scripts/backfill_image_classifications.py --provider openai --model gpt-4o --limit 10
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

from src.infra.db import DatabaseAdapter  # noqa: E402
from src.infra.image_storage import InvalidStorageKeyError, get_image_storage  # noqa: E402
from src.infra.logging_config import configure_logging  # noqa: E402

logger = logging.getLogger(__name__)

COST_PER_CALL_ESTIMATE_USD: float = 0.0005
PROMPT_VERSION: int = 1


def _build_vision_client(provider: str, model: str):  # type: ignore[return]
    from src.extraction_v2.stages.image_classify import _build_client

    return _build_client(provider, model)


def _fetch_eligible_images(db: DatabaseAdapter) -> list[dict]:
    return db.query(
        """
        SELECT
            ia.img_id::text AS img_id,
            ia.file_path,
            ia.classification,
            COUNT(imc.id) AS confirmation_count
        FROM v2_image_assets ia
        JOIN v2_image_metric_confirmations imc ON imc.img_id = ia.img_id
        WHERE ia.classification IN ('chart', 'table_image')
          AND ia.file_path IS NOT NULL
          AND NOT starts_with(ia.file_path, '/')
          AND NOT EXISTS (
              SELECT 1
              FROM v2_image_classifications vic
              WHERE vic.img_id = ia.img_id
                AND jsonb_array_length(vic.predicted_metrics) > 0
          )
        GROUP BY ia.img_id, ia.file_path, ia.classification
        ORDER BY confirmation_count ASC, ia.img_id
        """,
    )


def _insert_classification(db: DatabaseAdapter, record: dict) -> None:
    with db.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO v2_image_classifications (
                    img_id,
                    predicted_metrics,
                    confidence,
                    rejection_reason,
                    reasoning,
                    provider,
                    model,
                    prompt_version,
                    cost_usd,
                    latency_ms
                ) VALUES (
                    %(img_id)s::uuid,
                    %(predicted_metrics)s::jsonb,
                    %(confidence)s,
                    %(rejection_reason)s,
                    %(reasoning)s,
                    %(provider)s,
                    %(model)s,
                    %(prompt_version)s,
                    %(cost_usd)s,
                    %(latency_ms)s
                )
                """,
                record,
            )


def run(
    db: DatabaseAdapter,
    *,
    provider: str,
    model: str,
    limit: int | None,
    dry_run: bool,
    max_spend_usd: float | None,
    batch_size: int,
) -> dict:
    eligible = _fetch_eligible_images(db)
    eligible_count = len(eligible)

    if dry_run:
        to_process = eligible[:limit] if limit is not None else eligible
        estimated_cost = len(to_process) * COST_PER_CALL_ESTIMATE_USD
        print(f"Dry-run: {eligible_count} eligible images ({len(to_process)} would be processed).")
        print(
            f"Estimated cost: ${estimated_cost:.4f}"
            f" (rough — actual depends on image size and prompt length)"
        )
        return {
            "eligible": eligible_count,
            "processed": 0,
            "successes": 0,
            "api_errors": 0,
            "parse_failures": 0,
            "total_cost_usd": 0.0,
        }

    to_process = eligible[:limit] if limit is not None else eligible

    client = _build_vision_client(provider, model)
    storage = get_image_storage()

    successes = 0
    api_errors = 0
    parse_failures = 0
    total_cost_usd = 0.0
    wall_start = time.monotonic()

    for i, row in enumerate(to_process, 1):
        img_id = row["img_id"]
        file_path = row["file_path"]

        if max_spend_usd is not None and total_cost_usd >= max_spend_usd:
            logger.warning(
                "max_spend_usd=%.4f reached after %d images — aborting",
                max_spend_usd,
                i - 1,
            )
            break

        try:
            image_bytes = storage.get_bytes(file_path)
        except (FileNotFoundError, OSError, InvalidStorageKeyError) as exc:
            logger.warning("img_id=%s: missing bytes path=%s err=%s", img_id, file_path, exc)
            api_errors += 1
            continue

        t0 = time.perf_counter()
        try:
            parsed = client.analyze_image_for_metric_classification(image_bytes=image_bytes)
        except Exception:
            logger.exception("img_id=%s: vision API call failed", img_id)
            api_errors += 1
            continue
        latency_ms = int((time.perf_counter() - t0) * 1000)

        if parsed is None:
            logger.warning("img_id=%s: vision API returned None", img_id)
            api_errors += 1
            continue

        cost_usd = float(parsed.pop("_cost_usd", 0.0))

        try:
            predicted_metrics = [
                {"metric_id": m, "score": parsed["confidence"]} for m in parsed["predicted_metrics"]
            ]
        except (KeyError, TypeError) as exc:
            logger.warning("img_id=%s: parse failure err=%s parsed=%r", img_id, exc, parsed)
            parse_failures += 1
            continue

        record = {
            "img_id": img_id,
            "predicted_metrics": json.dumps(predicted_metrics),
            "confidence": parsed["confidence"],
            "rejection_reason": parsed.get("rejection_reason"),
            "reasoning": parsed.get("reasoning") or None,
            "provider": provider,
            "model": model,
            "prompt_version": PROMPT_VERSION,
            "cost_usd": cost_usd,
            "latency_ms": latency_ms,
        }

        try:
            _insert_classification(db, record)
        except Exception:
            logger.exception("img_id=%s: DB insert failed", img_id)
            api_errors += 1
            continue

        total_cost_usd += cost_usd
        successes += 1
        logger.info(
            "img_id=%s: success cost_usd=%.6f latency_ms=%d",
            img_id,
            cost_usd,
            latency_ms,
        )

        if i % batch_size == 0:
            logger.info(
                "Progress: %d/%d processed successes=%d api_errors=%d"
                " parse_failures=%d cost_usd=%.4f",
                i,
                len(to_process),
                successes,
                api_errors,
                parse_failures,
                total_cost_usd,
            )

    wall_time = time.monotonic() - wall_start
    processed = successes + api_errors + parse_failures

    return {
        "eligible": eligible_count,
        "processed": processed,
        "successes": successes,
        "api_errors": api_errors,
        "parse_failures": parse_failures,
        "total_cost_usd": total_cost_usd,
        "wall_time_s": wall_time,
    }


def _print_summary(stats: dict) -> None:
    print("Backfill complete:")
    print(f"  Eligible images:        {stats['eligible']}")
    print(f"  Processed:              {stats['processed']}")
    print(f"  Successes:              {stats['successes']}")
    print(f"  API errors:             {stats['api_errors']}")
    print(f"  Parse failures:         {stats['parse_failures']}")
    print(f"  Total cost (USD):       ${stats['total_cost_usd']:.4f}")
    if "wall_time_s" in stats:
        print(f"  Total wall time:        {stats['wall_time_s']:.1f} seconds")


def main() -> None:
    from src.extraction_v2.pipeline import PipelineConfig

    defaults = PipelineConfig()
    default_provider = defaults.vision_classify_provider
    default_model = defaults.vision_classify_model

    parser = argparse.ArgumentParser(
        description="Backfill v2_image_classifications for reviewed images."
    )
    parser.add_argument("--limit", type=int, default=None, help="Max images to process.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Count eligible images and estimate cost without making API calls.",
    )
    parser.add_argument(
        "--max-spend-usd",
        type=float,
        default=None,
        dest="max_spend_usd",
        help="Abort when cumulative spend exceeds this threshold (USD).",
    )
    parser.add_argument(
        "--provider",
        default=default_provider,
        help=f"VisionClient provider (default: {default_provider}).",
    )
    parser.add_argument(
        "--model",
        default=default_model,
        help=f"VisionClient model (default: {default_model}).",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=25,
        dest="batch_size",
        help="Log progress every N images (default: 25).",
    )
    parser.add_argument(
        "--database-url",
        default=None,
        dest="database_url",
        help="Override DATABASE_URL.",
    )
    args = parser.parse_args()

    configure_logging()

    db_url = args.database_url or os.environ.get("DATABASE_URL")
    if not db_url:
        print("ERROR: DATABASE_URL not set and --database-url not provided.", file=sys.stderr)
        sys.exit(1)

    db = DatabaseAdapter(db_url)

    stats = run(
        db,
        provider=args.provider,
        model=args.model,
        limit=args.limit,
        dry_run=args.dry_run,
        max_spend_usd=args.max_spend_usd,
        batch_size=args.batch_size,
    )

    if not args.dry_run:
        _print_summary(stats)


if __name__ == "__main__":
    main()
