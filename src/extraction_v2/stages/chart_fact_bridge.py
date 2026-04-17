from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
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
        filing_date = context.document_date or date.today()
        doc_id = str(context.filing_id)

        items_processed = 0
        items_output = 0

        for image in context.images:
            if image.chart_data is None:
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
                    value_raw = str(ann.value) if ann.value is not None else ""
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
                    context.facts.append(fact)
                    items_output += 1
            else:
                for series in chart.series:
                    for point in series.points:
                        cohort_period = parser.parse(chart, series, point, filing_date)
                        if cohort_period is None:
                            continue
                        value_raw = point.label if point.label is not None else str(point.y)
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
                        context.facts.append(fact)
                        items_output += 1

        duration_ms = int((datetime.now(UTC) - start_time).total_seconds() * 1000)
        return StageResult(
            stage=PipelineStage.CHART_FACT_BRIDGE,
            success=True,
            duration_ms=duration_ms,
            items_processed=items_processed,
            items_output=items_output,
        )
