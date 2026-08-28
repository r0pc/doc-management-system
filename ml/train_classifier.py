"""Kaggle-side trainer for the DMS classifiers.

ALL heavy imports (torch / sentence_transformers / sklearn / joblib / pandas) happen inside
functions -- the host machine has none of them; Kaggle does. Run top-to-bottom on Kaggle or
locally wherever the heavy stack exists.

Outputs (into --out-dir):
  model.joblib  {"manifest": {...}, "models": {"doc_type": {"model", "label_encoder"},
                                                "security_level": {"model", "label_encoder"}}}
  metrics.json  identical to manifest["metrics"]

Metrics are reported per source slice ("synthetic" / "real"; real may be absent -> null) as
per-class recall with restricted_recall called out explicitly. A lone accuracy number is
never printed or stored on its own (AGENTS.md invariants #13/#14).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

EMBEDDING_MODEL_ID = "BAAI/bge-small-en-v1.5"
EXPECTED_DIM = 384
TARGETS = (("doc_type", "label_doc_type"), ("security_level", "label_level"))
SLICES = ("synthetic", "real")


def _encode(texts: list[str]):
    import numpy as np
    from sentence_transformers import SentenceTransformer

    model = SentenceTransformer(EMBEDDING_MODEL_ID)
    embeddings = model.encode([t[:4000] for t in texts], show_progress_bar=False)
    array = np.asarray(embeddings)
    if array.shape[1] != EXPECTED_DIM:
        raise SystemExit(
            f"embedding dim {array.shape[1]} != contract dim {EXPECTED_DIM}"
        )
    return array


def _split_indices(train_test_split, y, random_state: int, test_size: float):
    import numpy as np

    try:
        train_idx, test_idx = train_test_split(
            np.arange(len(y)), test_size=test_size, random_state=random_state, stratify=y
        )
    except ValueError:
        print("warning: classes too small for stratified split; using unstratified split")
        train_idx, test_idx = train_test_split(
            np.arange(len(y)), test_size=test_size, random_state=random_state
        )
    return train_idx, test_idx


def _fit_calibrated(clf_classes, y_train):
    from sklearn.calibration import CalibratedClassifierCV
    from sklearn.linear_model import LogisticRegression

    min_class = min((y_train == c).sum() for c in clf_classes)
    cv = max(2, min(5, int(min_class)))
    base = LogisticRegression(max_iter=1000, class_weight="balanced")
    return CalibratedClassifierCV(base, method="sigmoid", cv=cv)


def _slice_metrics(recall_score, y_true, y_pred, classes) -> dict:
    values = recall_score(
        y_true, y_pred, labels=list(range(len(classes))), average=None, zero_division=0
    )
    per_class = {str(c): round(float(v), 4) for c, v in zip(classes, values, strict=True)}
    return {
        "support": int(len(y_true)),
        "per_class_recall": per_class,
        "restricted_recall": per_class.get("Restricted"),
    }


def _report(target: str, slice_name: str, metrics: dict | None) -> None:
    if metrics is None:
        print(f"  [{target}/{slice_name}] no rows -> null")
        return
    print(f"  [{target}/{slice_name}] support={metrics['support']}")
    for label, recall in sorted(metrics["per_class_recall"].items()):
        print(f"    recall[{label}] = {recall}")
    if metrics["restricted_recall"] is not None:
        print(f"    restricted_recall = {metrics['restricted_recall']}  <- highest-label gate")


def main(argv: list[str] | None = None) -> int:
    import joblib
    import pandas as pd
    import sklearn
    from sklearn.model_selection import train_test_split
    from sklearn.preprocessing import LabelEncoder

    parser = argparse.ArgumentParser(description="Train the DMS classifiers on a dataset.")
    parser.add_argument("--dataset", type=Path, default=Path("dataset.csv"))
    parser.add_argument("--out-dir", type=Path, default=Path("."))
    parser.add_argument("--test-size", type=float, default=0.2)
    parser.add_argument("--random-state", type=int, default=42)
    args = parser.parse_args(argv)

    frame = pd.read_csv(args.dataset)
    texts = frame["text_excerpt"].astype(str).tolist()
    sources = frame["source"].astype(str).to_numpy()
    print(f"Loaded {len(texts)} rows from {args.dataset}; encoding with {EMBEDDING_MODEL_ID} ...")
    embeddings = _encode(texts)

    manifest_metrics: dict[str, dict] = {}
    models: dict[str, dict] = {}
    labels_out: dict[str, list[str]] = {}

    for target, column in TARGETS:
        encoder = LabelEncoder()
        y_all = encoder.fit_transform(frame[column].astype(str).to_numpy())
        classes = encoder.classes_
        labels_out[target] = sorted(str(c) for c in classes)

        train_idx, test_idx = _split_indices(
            train_test_split, y_all, args.random_state, args.test_size
        )
        x_train, x_test = embeddings[train_idx], embeddings[test_idx]
        y_train, y_test = y_all[train_idx], y_all[test_idx]
        src_test = sources[test_idx]

        clf = _fit_calibrated(classes, y_train)
        clf.fit(x_train, y_train)
        y_pred = clf.predict(x_test)

        target_metrics: dict[str, dict | None] = {}
        for slice_name in SLICES:
            mask = src_test == slice_name
            if not mask.any():
                target_metrics[slice_name] = None
                continue
            from sklearn.metrics import recall_score

            target_metrics[slice_name] = _slice_metrics(
                recall_score, y_test[mask], y_pred[mask], classes
            )
            _report(target, slice_name, target_metrics[slice_name])

        manifest_metrics[target] = target_metrics
        models[target] = {"model": clf, "label_encoder": encoder}

    manifest = {
        "schema_version": 1,
        "sklearn_version": sklearn.__version__,
        "embedding_model_id": EMBEDDING_MODEL_ID,
        "dim": int(embeddings.shape[1]),
        "labels": labels_out,
        "metrics": manifest_metrics,
    }
    artifact = {"manifest": manifest, "models": models}

    args.out_dir.mkdir(parents=True, exist_ok=True)
    joblib.dump(artifact, args.out_dir / "model.joblib")
    (args.out_dir / "metrics.json").write_text(
        json.dumps(manifest_metrics, indent=2, sort_keys=True), encoding="utf-8"
    )
    print(f"Wrote {args.out_dir / 'model.joblib'} and {args.out_dir / 'metrics.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
