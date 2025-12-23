#!/usr/bin/env python3
"""Train a lightweight TF-IDF + logistic regression classifier for metric segments."""

import argparse
import csv
from pathlib import Path
from typing import List, Tuple

from joblib import dump
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import classification_report
from sklearn.multiclass import OneVsRestClassifier
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import MultiLabelBinarizer


def load_dataset(csv_path: Path) -> Tuple[List[str], List[List[str]]]:
    texts: List[str] = []
    labels: List[List[str]] = []

    with csv_path.open() as f:
        reader = csv.DictReader(f)
        for row in reader:
            label_tokens = [token.strip() for token in row["labels"].split("|") if token.strip()]
            texts.append(row["text"])
            labels.append(label_tokens)

    return texts, labels


def train_model(
    csv_path: Path,
    model_path: Path,
    test_size: float = 0.25,
    random_state: int = 42,
) -> None:
    texts, labels = load_dataset(csv_path)

    vectorizer = TfidfVectorizer(ngram_range=(1, 2), max_features=5000)
    X = vectorizer.fit_transform(texts)

    label_binarizer = MultiLabelBinarizer()
    y = label_binarizer.fit_transform(labels)

    classifier = OneVsRestClassifier(LogisticRegression(max_iter=2000, solver="liblinear"))

    if len(texts) > 4:
        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=test_size, random_state=random_state
        )
    else:
        X_train, X_test, y_train, y_test = X, X, y, y

    classifier.fit(X_train, y_train)

    y_pred = classifier.predict(X_test)
    report = classification_report(
        y_test,
        y_pred,
        target_names=label_binarizer.classes_,
        zero_division=0,
    )

    model_path.parent.mkdir(parents=True, exist_ok=True)
    dump(
        {
            "vectorizer": vectorizer,
            "classifier": classifier,
            "label_binarizer": label_binarizer,
        },
        model_path,
    )

    print(f"Saved model to {model_path}")
    print("\nEvaluation on held-out set:")
    print(report)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--data",
        type=Path,
        default=Path("data/training/metric_classifier_labeled.csv"),
        help="Path to CSV file with columns [text, labels]",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/models/metric_classifier.joblib"),
        help="Where to store the trained model bundle",
    )

    args = parser.parse_args()
    train_model(args.data, args.output)


if __name__ == "__main__":
    main()
