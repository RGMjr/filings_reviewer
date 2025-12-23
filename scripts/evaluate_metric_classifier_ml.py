#!/usr/bin/env python3
"""Evaluate learned metric classifier against rule-based baseline."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from joblib import load
from sklearn.metrics import precision_recall_fscore_support
from sklearn.preprocessing import MultiLabelBinarizer

PROJECT_ROOT = Path(__file__).parent.parent


def prepare_environment() -> None:
    """Ensure the repository root is on sys.path for src imports."""
    project_root_str = str(PROJECT_ROOT)
    if project_root_str not in sys.path:
        sys.path.insert(0, project_root_str)

LabelSet = set[str]


class LearnedMetricClassifier:
    """Lightweight wrapper for the trained TF-IDF + logistic regression model."""

    def __init__(
        self,
        model_path: Path,
        fallback_predictor: Callable[[str], LabelSet] | None = None,
    ) -> None:
        bundle = load(model_path)
        self.vectorizer = bundle["vectorizer"]
        self.classifier = bundle["classifier"]
        self.label_binarizer = bundle["label_binarizer"]
        self._fallback_predictor = fallback_predictor

    def predict_labels(self, text: str) -> LabelSet:
        features = self.vectorizer.transform([text])
        prediction = self.classifier.predict(features)
        inverse = self.label_binarizer.inverse_transform(prediction)
        learned_labels = set(inverse[0]) if inverse else set()

        if self._fallback_predictor is not None:
            # Mimic the historical "regex fallback" behavior.
            return learned_labels | self._fallback_predictor(text)

        return learned_labels


def load_dataset(csv_path: Path) -> list[tuple[str, LabelSet]]:
    dataset = []
    with csv_path.open() as f:
        reader = csv.DictReader(f)
        for row in reader:
            labels = {token.strip() for token in row["labels"].split("|") if token.strip()}
            dataset.append((row["text"], labels))
    return dataset


def evaluate(
    dataset: list[tuple[str, LabelSet]],
    predict_fn: Callable[[str], LabelSet],
) -> tuple[float, float, float]:
    predictions: list[LabelSet] = []
    truths: list[LabelSet] = []

    for text, labels in dataset:
        predictions.append(predict_fn(text))
        truths.append(labels)

    binarizer = MultiLabelBinarizer()
    binarizer.fit(truths + predictions)
    y_true = binarizer.transform(truths)
    y_pred = binarizer.transform(predictions)
    precision, recall, f1, _ = precision_recall_fscore_support(
        y_true, y_pred, average="micro", zero_division=0
    )
    return precision, recall, f1


def write_metrics_log(output_path: Path, payload: dict) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("a") as f:
        f.write(json.dumps(payload) + "\n")


def main() -> None:
    prepare_environment()

    from src.extraction.metric_classifier import MetricClassifier
    from src.extraction.models import SourceSegment

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--data",
        type=Path,
        default=Path("data/training/metric_classifier_labeled.csv"),
        help="Dataset CSV with columns [text, labels]",
    )
    parser.add_argument(
        "--model",
        type=Path,
        default=Path("data/models/metric_classifier.joblib"),
        help="Path to learned model bundle",
    )
    parser.add_argument(
        "--log-path",
        type=Path,
        default=Path("logs/metric_classifier_eval.jsonl"),
        help="Where to append evaluation metrics",
    )
    args = parser.parse_args()

    dataset = load_dataset(args.data)

    def segment_from_text(text: str) -> SourceSegment:
        return SourceSegment(
            filing_id=0,
            segment_type="paragraph",
            raw_text=text,
        )

    def labels_from_segment(segment: SourceSegment) -> LabelSet:
        labels: LabelSet = set()
        if segment.contains_definition_flag:
            labels.add("definition")
        if segment.contains_methodology_flag:
            labels.add("methodology")
        if segment.contains_numeric_disclosure_flag:
            labels.add("numeric")
        for metric_id in segment.candidate_metric_ids:
            labels.add(f"metric:{metric_id}")
        return labels

    baseline_classifier = MetricClassifier()

    def predict_with_baseline(text: str) -> LabelSet:
        segment = baseline_classifier.classify_segment(segment_from_text(text), validate=False)
        return labels_from_segment(segment)

    learned_classifier = LearnedMetricClassifier(
        args.model,
        fallback_predictor=predict_with_baseline,
    )

    base_precision, base_recall, base_f1 = evaluate(dataset, predict_with_baseline)
    learned_precision, learned_recall, learned_f1 = evaluate(
        dataset, learned_classifier.predict_labels
    )

    print("Rule-based baseline (regex + heuristics):")
    print(f"  Precision: {base_precision:.3f}\n  Recall:    {base_recall:.3f}\n  F1:        {base_f1:.3f}\n")

    print("Hybrid learned classifier (learned + regex fallback):")
    print(
        f"  Precision: {learned_precision:.3f}\n  Recall:    {learned_recall:.3f}\n  F1:        {learned_f1:.3f}\n"
    )

    payload = {
        "timestamp": datetime.now(UTC).isoformat(),
        "dataset": str(args.data),
        "model": str(args.model),
        "baseline": {
            "precision": base_precision,
            "recall": base_recall,
            "f1": base_f1,
        },
        "learned": {
            "precision": learned_precision,
            "recall": learned_recall,
            "f1": learned_f1,
        },
    }
    write_metrics_log(args.log_path, payload)
    print(f"Metrics appended to {args.log_path}")


if __name__ == "__main__":
    main()
