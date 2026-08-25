# Model Artifact Contract — schema_version 1

This document is the single authority for the `model.joblib` artifact produced by
`ml/train_classifier.py` (or `ml/train_template.ipynb`) and consumed by the backend
classification loader (Wave 2.C builds against THIS document).

## Canonical synthetic entity formats (mirrored by backend validators)

`ml/entities.py` is the single source. Backend validators must mirror, not re-derive:

| Entity | Format | Notes |
|---|---|---|
| CNIC | `P####-#######-#` (5-7-1 digit groups) | province `P ∈ {1,2,3,4,5,7,8}`; 0/6/9 invalid per spec §3.2 |
| Card | 16 digits | must pass Luhn (`luhn_valid`) |
| Passport | `[A-Z]{2}\d{7}` | e.g. `KP1234567` |
| Account | `PK[A-Z]{2}\d{13}` (17 chars) | length + prefix only in phase 1; **no IBAN checksum** (documented deviation) |

Per-level entity counts follow spec §3.7 verbatim (`SPECS` in `entities.py`). Card counts are
derived: restricted records carry 1–2 cards, others none. Passports: restricted-only 0–1
(phase-1 choice). Literal `PKR <amount>` text is reserved for salary lines across all templates.

## Artifact layout

```
model.joblib (joblib.dump)
├── manifest
│   ├── schema_version: 1
│   ├── sklearn_version: "<x.y.z>"          # e.g. "1.5.2"
│   ├── embedding_model_id: "BAAI/bge-small-en-v1.5"
│   ├── dim: 384
│   ├── labels
│   │   ├── doc_type: sorted unique slugs   # subset of taxonomy below
│   │   └── security_level: sorted unique   # subset of taxonomy below
│   └── metrics                             # same object as metrics.json
│       ├── doc_type:       {"synthetic": {...}|null, "real": {...}|null}
│       └── security_level: {"synthetic": {...}|null, "real": {...}|null}
│            each slice: {support, per_class_recall: {label: float}, restricted_recall: float|null}
└── models
    ├── doc_type:        {"model": CalibratedClassifierCV, "label_encoder": LabelEncoder}
    └── security_level:  {"model": CalibratedClassifierCV, "label_encoder": LabelEncoder}
```

Taxonomy subsets:

- `doc_type` ⊆ {contract, vendor_msa, invoice, hr_letter, disciplinary_notice, monthly_report, policy_memo}
- `security_level` ⊆ {Public, Internal, Confidential, Restricted}

## Compatibility rules (loader MUST enforce all)

1. `schema_version == 1`; anything else is rejected, not migrated.
2. `sklearn_version` major.minor must equal the backend's installed scikit-learn major.minor.
   Patch differences are tolerated.
3. `dim == 384` and `embedding_model_id == "BAAI/bge-small-en-v1.5"`; the backend encodes with
   the identical model id before predicting.
4. Every label in `manifest.labels.*` must be a member of the backend taxonomy at load time.
5. `metrics.real` may be `null` (real slice absent). `restricted_recall`, when present, is an
   operational gate: hold it near 1.0 before promoting a model (invariant #14).

## How the backend loader consumes this (Wave 2.C)

1. Load with `joblib.load`; validate the manifest against the rules above.
2. Encode candidate text (first 4000 chars) with the pinned sentence-transformers model.
3. Predict both targets via the stored calibrated heads + label encoders.
4. The security-level output enters the aggregation pipeline as a **proposal**: monotonicity
   (`check_monotonic` trigger), human-review routing (<0.85 ML confidence → review), and audit
   rules live in the backend, never in this artifact.
5. Metrics slices are reported separately forever; synthetic numbers never stand in for real
   accuracy (invariant #13).
