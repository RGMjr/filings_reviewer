from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from src.extraction_v2.chart.cohort_parser import CohortParser
from src.extraction_v2.chart.metric_classifier import ChartMetricClassifier
from src.extraction_v2.chart.unit_inference import infer_unit_and_currency
from src.extraction_v2.models import (
    EvidencePack,
    MetricFact,
    PeriodType,
    Scope,
    SourceLocator,
    SourceType,
    Unit,
)

if TYPE_CHECKING:
    from src.extraction_v2.pipeline import PipelineContext, StageResult

logger = logging.getLogger(__name__)

_CURRENCY_OR_COUNT_METRICS = frozenset({
    "cm_revenue_by_cohort",
    "cm_transactions_by_cohort",
    "cm_balance_by_cohort",
    # Add new currency/count cohort metrics here if the classifier targets them
})


def _annotation_compatible_with_metric(metric_id: str, ann: object) -> bool:
    if getattr(ann, "unit", None) == "percent" and metric_id in _CURRENCY_OR_COUNT_METRICS:
        return False
    return True


class ChartFactBridgeStage:
    def process(self, context: PipelineContext) -> StageResult:
        from src.extraction_v2.pipeline import PipelineStage, StageResult

        start_time = datetime.now(UTC)

        if not context.config.enable_chart_fact_bridge:
            duration_ms = int((datetime.now(UTC) - start_time).total_seconds() * 1000)
            return StageResult(
                stage=PipelineStage.CHART_FACT_BRIDGE,
                success=True,
                duration_ms=duration_ms,
                items_processed=0,
                items_output=0,
            )

        classifier = ChartMetricClassifier()
        parser = CohortParser()
        filing_date = context.document_date
        if filing_date is None:
            logger.warning(
                "ChartFactBridgeStage: no document_date on context for filing_id=%s; skipping chart fact emission",
                context.filing_id,
            )
            duration_ms = int((datetime.now(UTC) - start_time).total_seconds() * 1000)
            return StageResult(
                stage=PipelineStage.CHART_FACT_BRIDGE,
                success=True,
                duration_ms=duration_ms,
                items_processed=0,
                items_output=0,
            )
        doc_id = str(context.filing_id)

        items_processed = 0
        items_output = 0

        # Guard counters — initialised before the image loop
        result_metadata: dict = {
            "guard_skipped_low_image_confidence": 0,
            "guard_skipped_missing_label": 0,
            "guard_skipped_out_of_range": 0,
            "guard_skipped_future_cohort": 0,
        }

        for image in context.images:
            if image.chart_data is None:
                continue

            # Guard 1 — image confidence gate
            if (
                image.confidence is not None
                and image.confidence < context.config.chart_image_min_confidence
            ):
                result_metadata["guard_skipped_low_image_confidence"] += 1
                continue

            items_processed += 1
            chart = image.chart_data

            metric_id, score = classifier.classify(chart, image.nearby_text or "")
            if metric_id is None or score < context.config.chart_metric_classification_min_score:
                continue

            unit, currency = infer_unit_and_currency(chart.y_axis_label)
            if unit is None:
                unit = Unit.OTHER

            annotations_only = not chart.series or all(not s.points for s in chart.series)

            if annotations_only:
                cohort_period = parser.parse(chart, None, None, filing_date)
                if cohort_period is None:
                    continue
                for ann in chart.annotations:
                    if ann.value is None:
                        continue
                    if not _annotation_compatible_with_metric(metric_id, ann):
                        continue
                    value_raw = str(ann.value)
                    fact = MetricFact(
                        fact_id=str(uuid.uuid4()),
                        doc_id=doc_id,
                        canonical_metric_id=metric_id,
                        value=ann.value,
                        value_raw=value_raw,
                        unit=unit,
                        currency=currency,
                        period_type=PeriodType.POINT_IN_TIME,
                        period_start=cohort_period.period_start,
                        period_end=cohort_period.period_end,
                        scope=Scope.COMPANY,
                        cohort_def=cohort_period.cohort_def,
                        source_type=SourceType.CHART,
                        source_locator=SourceLocator(img_id=image.img_id, bbox=None),
                        evidence_pack=EvidencePack(
                            snippet_html="",
                            raw_value_text=value_raw,
                            context_before=f"Chart: {chart.title}",
                        ),
                        confidence=0.55,
                        requires_review=True,
                    )
                    # Guard 5 — fact review threshold (annotations branch already sets True;
                    # keep consistent by applying the threshold check uniformly)
                    if fact.confidence < context.config.chart_fact_review_threshold:
                        fact.requires_review = True
                    context.facts.append(fact)
                    items_output += 1
            elif metric_id == "cm_ltv_to_cac_ratio":
                for series in chart.series:
                    # Guard 3 — axis-range sanity: compute reference max from labeled points
                    labeled_points = [p for p in series.points if p.label is not None]
                    if labeled_points:
                        labeled_max = max(abs(p.y) for p in labeled_points)
                    else:
                        labeled_max = 0.0

                    for point in series.points:
                        # Guard 3 — axis-range sanity (runs before label guard so it can
                        # reject unlabeled noise points that exceed the labeled reference range)
                        if labeled_max > 0 and abs(point.y) > labeled_max * context.config.chart_axis_range_multiplier:
                            result_metadata["guard_skipped_out_of_range"] += 1
                            continue

                        # Guard 2 — label-required gate
                        if point.label is None:
                            result_metadata["guard_skipped_missing_label"] += 1
                            continue

                        value_raw = point.label
                        fact = MetricFact(
                            fact_id=str(uuid.uuid4()),
                            doc_id=doc_id,
                            canonical_metric_id=metric_id,
                            value=point.y,
                            value_raw=value_raw,
                            unit=unit,
                            currency=currency,
                            period_type=PeriodType.POINT_IN_TIME,
                            period_start=filing_date,
                            period_end=filing_date,
                            scope=Scope.CUSTOMER_TYPE,
                            cohort_def=str(point.x),
                            source_type=SourceType.CHART,
                            source_locator=SourceLocator(img_id=image.img_id, bbox=point.bbox),
                            evidence_pack=EvidencePack(
                                snippet_html="",
                                raw_value_text=value_raw,
                                context_before=f"Chart: {chart.title}",
                            ),
                            confidence=0.80,
                            requires_review=False,
                        )
                        # Guard 5 — fact review threshold
                        if fact.confidence < context.config.chart_fact_review_threshold:
                            fact.requires_review = True
                        context.facts.append(fact)
                        items_output += 1
            else:
                for series in chart.series:
                    # Guard 3 — axis-range sanity: compute reference max from labeled points
                    labeled_points = [p for p in series.points if p.label is not None]
                    if labeled_points:
                        labeled_max = max(abs(p.y) for p in labeled_points)
                    else:
                        labeled_max = 0.0

                    for point in series.points:
                        # Guard 3 — axis-range sanity (runs before label guard so it can
                        # reject unlabeled noise points that exceed the labeled reference range)
                        if labeled_max > 0 and abs(point.y) > labeled_max * context.config.chart_axis_range_multiplier:
                            result_metadata["guard_skipped_out_of_range"] += 1
                            continue

                        # Guard 2 — label-required gate
                        if point.label is None:
                            result_metadata["guard_skipped_missing_label"] += 1
                            continue

                        cohort_period = parser.parse(chart, series, point, filing_date)
                        if cohort_period is None:
                            continue

                        # Guard 4 — cohort-year sanity (default cohort branch only)
                        if cohort_period.period_end.year > filing_date.year + 1:
                            result_metadata["guard_skipped_future_cohort"] += 1
                            continue

                        value_raw = point.label
                        fact = MetricFact(
                            fact_id=str(uuid.uuid4()),
                            doc_id=doc_id,
                            canonical_metric_id=metric_id,
                            value=point.y,
                            value_raw=value_raw,
                            unit=unit,
                            currency=currency,
                            period_type=PeriodType.POINT_IN_TIME,
                            period_start=cohort_period.period_start,
                            period_end=cohort_period.period_end,
                            scope=Scope.COMPANY,
                            cohort_def=cohort_period.cohort_def,
                            source_type=SourceType.CHART,
                            source_locator=SourceLocator(img_id=image.img_id, bbox=point.bbox),
                            evidence_pack=EvidencePack(
                                snippet_html="",
                                raw_value_text=value_raw,
                                context_before=f"Chart: {chart.title}",
                            ),
                            confidence=cohort_period.confidence,
                            requires_review=cohort_period.requires_review,
                        )
                        # Guard 5 — fact review threshold
                        if fact.confidence < context.config.chart_fact_review_threshold:
                            fact.requires_review = True
                        context.facts.append(fact)
                        items_output += 1

        duration_ms = int((datetime.now(UTC) - start_time).total_seconds() * 1000)
        return StageResult(
            stage=PipelineStage.CHART_FACT_BRIDGE,
            success=True,
            duration_ms=duration_ms,
            items_processed=items_processed,
            items_output=items_output,
            metadata=result_metadata,
        )
