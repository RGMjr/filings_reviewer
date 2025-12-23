#!/usr/bin/env python3
"""Evaluate learned metric classifier against rule-based baseline."""

import argparse
import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Set

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from sklearn.metrics import precision_recall_fscore_support
from sklearn.preprocessing import MultiLabelBinarizer

from src.extraction.metric_classifier import MetricClassifier, MetricClassifierConfig
from src.extraction.models import SourceSegment


LabelSet = Set[str]


def load_dataset(csv_path: Path) -> List[tuple]:
    dataset = []
    with csv_path.open() as f:
        reader = csv.DictReader(f)
        for row in reader:
            labels = {token.strip() for token in row["labels"].split("|") if token.strip()}
            dataset.append((row["text"], labels))
    return dataset


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


def evaluate(
    classifier: MetricClassifier, dataset: List[tuple]
) -> tuple[float, float, float]:
    predictions: List[LabelSet] = []
    truths: List[LabelSet] = []

    for text, labels in dataset:
        segment = classifier.classify_segment(segment_from_text(text), validate=False)
        predictions.append(labels_from_segment(segment))
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

    baseline_classifier = MetricClassifier()
    learned_classifier = MetricClassifier(
        config=MetricClassifierConfig(
            use_learned_classifier=True,
            learned_model_path=str(args.model),
            use_regex_fallback=True,
        )
    )

    base_precision, base_recall, base_f1 = evaluate(baseline_classifier, dataset)
    learned_precision, learned_recall, learned_f1 = evaluate(learned_classifier, dataset)

    print("Rule-based baseline (regex + heuristics):")
    print(f"  Precision: {base_precision:.3f}\n  Recall:    {base_recall:.3f}\n  F1:        {base_f1:.3f}\n")

    print("Hybrid learned classifier (learned + regex fallback):")
    print(
        f"  Precision: {learned_precision:.3f}\n  Recall:    {learned_recall:.3f}\n  F1:        {learned_f1:.3f}\n"
    )

    payload = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
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
