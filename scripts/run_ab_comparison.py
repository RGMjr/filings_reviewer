#!/usr/bin/env python3
"""A/B comparison of vision providers on chart images from an SEC filing.

Runs both OpenAI GPT-4o and Claude Vision on all chart images in a filing,
then reports on data point counts, chart type agreement, value agreement,
confidence scores, and cost estimates.

Usage:
    python3 scripts/run_ab_comparison.py \\
        --filing-path data/filings/example.html \\
        --output results/ab_comparison.json

    python3 scripts/run_ab_comparison.py \\
        --filing-path data/filings/example.html \\
        --metric-id cm_revenue \\
        --output results/revenue_comparison.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Ensure project root is on path when run as script
_project_root = Path(__file__).resolve().parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))


def _run_provider_on_image(
    provider: object,
    image_bytes: bytes,
    prompt: str,
) -> dict:
    """Run a single vision provider on one image and return result dict."""
    try:
        response = provider.analyze_image(image_bytes=image_bytes, prompt=prompt)
        return {
            "success": True,
            "content": response.content,
            "model": response.model,
            "prompt_tokens": response.prompt_tokens,
            "completion_tokens": response.completion_tokens,
            "cost_usd": response.cost_usd,
            "latency_ms": response.latency_ms,
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "content": "",
            "model": "",
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "cost_usd": 0.0,
            "latency_ms": 0,
        }


def _parse_chart_response(content: str) -> dict:
    """Parse chart JSON from LLM response, stripping code fences."""
    import json
    import re

    clean = re.sub(r"^```(?:json)?\s*\n?", "", content.strip(), flags=re.MULTILINE)
    clean = clean.rstrip("`").strip()
    try:
        return json.loads(clean)
    except json.JSONDecodeError:
        return {}


def _values_agree(v1: float, v2: float, tolerance: float = 0.05) -> bool:
    """Check if two numeric values agree within a relative tolerance."""
    if v1 == 0 and v2 == 0:
        return True
    denom = max(abs(v1), abs(v2))
    return abs(v1 - v2) / denom <= tolerance


def main() -> None:
    parser = argparse.ArgumentParser(
        description="A/B comparison of vision providers on chart images"
    )
    parser.add_argument(
        "--filing-path",
        required=True,
        type=Path,
        help="Path to the SEC filing HTML file",
    )
    parser.add_argument(
        "--metric-id",
        default=None,
        help="Optional metric ID filter (e.g. cm_revenue). Filters chart candidates.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("ab_comparison_results.json"),
        help="Path to write comparison JSON (default: ab_comparison_results.json)",
    )
    args = parser.parse_args()

    filing_path = args.filing_path
    if not filing_path.exists():
        print(f"ERROR: Filing not found: {filing_path}", file=sys.stderr)
        sys.exit(1)

    print(f"Running A/B comparison on: {filing_path}")

    # Run ingestion + triage to get chart images
    from src.extraction_v2.pipeline import PipelineConfig, PipelineContext, V2Pipeline
    from src.extraction_v2.stages.ingestion import IngestionStage
    from src.extraction_v2.stages.image_triage import ImageTriageStage
    from src.extraction_v2.models import ImageClassification

    config = PipelineConfig(enable_chart_extraction=False)  # Don't auto-process; we do it manually
    context = PipelineContext(
        html_path=filing_path,
        filing_id=0,
        config=config,
    )

    print("Ingesting filing...")
    ingestion = IngestionStage()
    ingestion.process(context)

    print(f"Triaging {len(context.images)} images...")
    triage = ImageTriageStage()
    triage.process(context)

    chart_images = [
        img for img in context.images
        if img.classification == ImageClassification.CHART
        and img.file_path is not None
    ]
    print(f"Found {len(chart_images)} chart images to compare")

    if not chart_images:
        print("No chart images found. Exiting.")
        sys.exit(0)

    # Build providers
    from src.llm.vision_factory import create_vision_provider

    try:
        openai_provider = create_vision_provider("openai")
    except Exception as e:
        print(f"WARNING: Could not create OpenAI provider: {e}", file=sys.stderr)
        openai_provider = None

    try:
        claude_provider = create_vision_provider("claude")
    except Exception as e:
        print(f"WARNING: Could not create Claude provider: {e}", file=sys.stderr)
        claude_provider = None

    if openai_provider is None and claude_provider is None:
        print("ERROR: Neither provider available. Check API keys.", file=sys.stderr)
        sys.exit(1)

    # Chart extraction prompt (simplified for comparison)
    PROMPT = """Analyze this chart and extract ONLY explicitly labeled data values.
Return JSON with keys: chart_type, title, confidence (0-1), series (array of {name, points: [{x, y}]}).
ONLY extract values with explicit labels on the chart."""

    # Run comparison
    results = []
    total_openai_cost = 0.0
    total_claude_cost = 0.0

    for i, img in enumerate(chart_images, 1):
        print(f"  [{i}/{len(chart_images)}] Comparing {img.filename}...")
        image_bytes = Path(img.file_path).read_bytes()

        openai_result = (
            _run_provider_on_image(openai_provider, image_bytes, PROMPT)
            if openai_provider else {"success": False, "error": "provider unavailable"}
        )
        claude_result = (
            _run_provider_on_image(claude_provider, image_bytes, PROMPT)
            if claude_provider else {"success": False, "error": "provider unavailable"}
        )

        total_openai_cost += openai_result.get("cost_usd", 0.0)
        total_claude_cost += claude_result.get("cost_usd", 0.0)

        # Parse chart data for comparison
        openai_chart = _parse_chart_response(openai_result.get("content", ""))
        claude_chart = _parse_chart_response(claude_result.get("content", ""))

        openai_type = openai_chart.get("chart_type", "unknown")
        claude_type = claude_chart.get("chart_type", "unknown")
        type_agrees = openai_type == claude_type

        # Count data points
        def _count_points(chart: dict) -> int:
            return sum(len(s.get("points", [])) for s in chart.get("series", []))

        openai_points = _count_points(openai_chart)
        claude_points = _count_points(claude_chart)

        # Value agreement: compare common (x, y) pairs within 5%
        def _extract_values(chart: dict) -> list[float]:
            vals = []
            for s in chart.get("series", []):
                for p in s.get("points", []):
                    try:
                        vals.append(float(p.get("y", 0)))
                    except (TypeError, ValueError):
                        pass
            return sorted(vals)

        openai_vals = _extract_values(openai_chart)
        claude_vals = _extract_values(claude_chart)
        agreed = 0
        compared = min(len(openai_vals), len(claude_vals))
        for v1, v2 in zip(sorted(openai_vals), sorted(claude_vals)):
            if _values_agree(v1, v2):
                agreed += 1
        value_agreement_pct = (agreed / compared * 100) if compared > 0 else None

        results.append({
            "img_id": img.img_id,
            "filename": img.filename,
            "nearby_text_snippet": img.nearby_text[:100],
            "openai": {
                "success": openai_result.get("success"),
                "model": openai_result.get("model", ""),
                "chart_type": openai_type,
                "data_points": openai_points,
                "confidence": openai_chart.get("confidence"),
                "cost_usd": openai_result.get("cost_usd", 0.0),
                "latency_ms": openai_result.get("latency_ms", 0),
                "error": openai_result.get("error"),
            },
            "claude": {
                "success": claude_result.get("success"),
                "model": claude_result.get("model", ""),
                "chart_type": claude_type,
                "data_points": claude_points,
                "confidence": claude_chart.get("confidence"),
                "cost_usd": claude_result.get("cost_usd", 0.0),
                "latency_ms": claude_result.get("latency_ms", 0),
                "error": claude_result.get("error"),
            },
            "comparison": {
                "chart_type_agrees": type_agrees,
                "openai_data_points": openai_points,
                "claude_data_points": claude_points,
                "value_agreement_pct": value_agreement_pct,
                "values_compared": compared,
            },
        })

    # Summary
    n = len(results)
    type_agreement_count = sum(1 for r in results if r["comparison"]["chart_type_agrees"])
    avg_value_agreement = None
    va_results = [r["comparison"]["value_agreement_pct"] for r in results if r["comparison"]["value_agreement_pct"] is not None]
    if va_results:
        avg_value_agreement = sum(va_results) / len(va_results)

    summary = {
        "filing": str(filing_path),
        "metric_id_filter": args.metric_id,
        "charts_compared": n,
        "chart_type_agreement_count": type_agreement_count,
        "chart_type_agreement_pct": (type_agreement_count / n * 100) if n > 0 else None,
        "avg_value_agreement_pct": avg_value_agreement,
        "total_openai_cost_usd": total_openai_cost,
        "total_claude_cost_usd": total_claude_cost,
    }

    output = {"summary": summary, "results": results}

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, indent=2))
    print(f"\nComparison complete. Results written to: {args.output}")
    print(f"  Charts compared: {n}")
    print(f"  Chart type agreement: {type_agreement_count}/{n}")
    if avg_value_agreement is not None:
        print(f"  Avg value agreement: {avg_value_agreement:.1f}%")
    print(f"  OpenAI total cost: ${total_openai_cost:.4f}")
    print(f"  Claude total cost: ${total_claude_cost:.4f}")


if __name__ == "__main__":
    main()
