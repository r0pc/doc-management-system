# Model Artifact Contract — schema_version 1

> **READ THIS BEFORE TRUSTING ANY NUMBER BELOW.** The artifact currently shipped
> (`backend/var/models/model.joblib`) has **never been evaluated on real
> documents**. Its `metrics.json` reports `"real": null` for both heads and
> 1.0 per-class recall across the board on a 600-sample synthetic slice. See
> [§Evaluation status](#evaluation-status--the-metrics-are-not-evidence).


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
2. Encode candidate text (first 4000 chars) with the pinned sentence-transformers model —
   **once**. The ingestion `embed` stage computes this vector, persists it on the derived
   artifact `docs-derived/{sha}/text.json`, and both `classify` (via
   `predict_type(..., embedding=...)`) and `build_index` (into `document_text.embedding`, which
   the pgvector search arm ranks on) reuse it. A second pass over the same text with the same
   model is a bug (invariant #6). `_predict_with_artifact` still encodes on demand when no
   precomputed vector is supplied, and re-encodes if the supplied one is the wrong width.
3. Predict both targets via the stored calibrated heads + label encoders. **Any** failure here —
   absent ML stack, malformed payload, a head raising on an unexpected feature shape — degrades
   to `None` plus a log line and routes the document to human review. A model problem must never
   fail ingestion.
3a. Model labels are training slugs; the persisted taxonomy is `doc_types`, seeded by migration
   0003 and admin-editable thereafter. `DOC_TYPE_LABEL_TO_TAXONOMY_NAME` translates the two, and
   resolution looks the resulting name up in `doc_types`. Model output **never** creates a
   taxonomy row: an unknown label, or a known name with no row, records `doc_type_id = NULL` and
   logs. Note `hr_letter` maps to "HR Letter", which migration 0003 does **not** seed — the
   seed's `HR` node is the parent category of `Disciplinary Notice`, not a letter type, and
   coarsening a leaf prediction onto its parent would record a type the model never predicted.
   Until an admin creates that row via `/v1/admin`, `hr_letter` predictions store NULL.
4. The security-level output enters the aggregation pipeline as a **proposal**: monotonicity
   (`check_monotonic` trigger), human-review routing (<0.85 ML confidence → review), and audit
   rules live in the backend, never in this artifact.
5. Metrics slices are reported separately forever; synthetic numbers never stand in for real
   accuracy (invariant #13).


---

## Evaluation status — the metrics are NOT evidence

`backend/var/models/metrics.json`, as of this writing:

| head | synthetic support | per-class recall | `restricted_recall` | real slice |
|---|---|---|---|---|
| `doc_type` | 600 | 1.0 on all 7 classes | n/a | **`null`** |
| `security_level` | 600 | 1.0 on all 3 classes | 1.0 | **`null`** |

**Perfect recall here is a red flag, not a result.** The evaluation corpus was
generated by `ml/generate_synthetic_corpus.py` from the deterministic templates
in `ml/templates.py`. Each class has its own fixed skeleton, so a document's
class is recoverable from surface form alone — boilerplate phrasing, section
order, field layout. A 384-d sentence embedding separates those trivially.
What the 1.0s measure is **template-fingerprint separability, not document
semantics**, and there is no reason to expect any of it to transfer to real
documents, which do not come from seven fixed moulds.

This matters beyond optimism about accuracy:

- **Invariant #14 is satisfied vacuously.** "Per-class recall on the highest
  label tracked near 1.0" is met by `restricted_recall = 1.0` — over synthetic
  data where the Restricted templates are the ones carrying CNIC/card/passport
  blocks. It is not evidence that a real Restricted document will be caught.
- **Invariant #13 is not yet satisfiable.** The held-out set it requires
  (150–200 hand-labelled documents, 50–100 of them real) does not exist. Until
  it does, synthetic and real accuracy cannot be "reported separately" because
  there is no real number to report.
- **The 0.85 cascade gate is uncalibrated.** 0.85 is the spec's default, not a
  measured operating point. Calibrated probabilities fitted on synthetic-only
  data are calibrated *to that distribution*.

### What the backend does about it

- `load_artifact` emits `artifact_metrics_synthetic_only` at **WARNING** on
  every load of an artifact whose `metrics.<head>.real` is `null`, naming the
  affected heads. Operators see it in the ordinary log stream; it is not
  something that has to be looked up.
- The cascade threshold is configurable via the **`ML_CONFIDENCE_THRESHOLD`**
  environment variable (set on the worker in `docker-compose.yml`, default
  `0.85`, validated to `(0, 1]` with a warning-and-default fallback). It can be
  raised the day someone measures a real operating point — no code change.
- Nothing else is claimed. Sub-threshold and failed predictions route to human
  review, and the security level is never taken from the model alone (the
  `check_monotonic` trigger and the Internal floor remain the authority).

### Exit criteria for this section

Delete this section only when `metrics.<head>.real` is non-null for both heads,
produced from a hold-out set that was **never** trained on (#13), with
`restricted_recall` reported on the real slice. Recalibrate
`ML_CONFIDENCE_THRESHOLD` against that slice at the same time.
`tests/classification/test_ml_loader_contract.py::test_the_shipped_artifact_reports_no_real_evaluation`
fails the moment a real slice appears, which is the reminder to come back here.

---

## Deployment — where the weights actually live

Self-hosting is a hard requirement: **document text may not leave the
deployment, and nothing may call a hosted API at inference time.** Two separate
artifacts, two deliberately different distribution choices.

### 1. The encoder (`BAAI/bge-small-en-v1.5`, ~130 MB) — baked into the image

`SentenceTransformer("BAAI/bge-small-en-v1.5")` downloads from huggingface.co on
first use. Left alone, that is a network call from the worker at inference time
— exactly what the invariant forbids. So `backend/Dockerfile`:

1. installs torch from the **CPU wheel index** (`download.pytorch.org/whl/cpu`)
   before `pip install ".[parsers,ml]"`, so the CUDA runtime is never pulled;
2. materialises the encoder into `/opt/hf-cache` **at image build time**, which
   is a supply-chain step like `pip install`, not an inference-time fetch;
3. sets `HF_HUB_OFFLINE=1` / `TRANSFORMERS_OFFLINE=1` for runtime, so an
   attempted download becomes a hard error rather than silent egress.

Air-gapped builds: pre-populate `/opt/hf-cache` from an internal mirror and drop
the download `RUN`, or mount a host cache over `/opt/hf-cache`.

Why baked and not mounted: the encoder is *pinned by the artifact contract*
(rule 3). It is not an operator choice, it never varies per deployment, and a
version skew between it and the stored `document_text.embedding` vectors would
silently corrupt search ranking. It belongs to the image, like a library.

### 2. The trained classifier (`model.joblib`, ~160 KB) — mounted, not baked

`backend/var/` is gitignored and AGENTS.md forbids committing model weights, so
the artifact is neither in version control nor in the image. `docker-compose.yml`
bind-mounts it **read-only** into api/worker/worker-ocr:

```yaml
volumes:
  - ./backend/var/models:/srv/app/var/models:ro
environment:
  MODEL_ARTIFACT_PATH: /srv/app/var/models/model.joblib
```

Why mounted and not baked:

- **It changes on a different clock than the code.** Retraining should not
  require rebuilding and redistributing the application image.
- **The image stays weight-free and redistributable.** Baking it would put
  tenant-derived training output into every copy of the image.
- **Object storage was rejected.** MinIO holds tenant documents; a self-hosted
  on-prem operator already has a filesystem, and adding a bucket fetch would put
  a network dependency (and a credential) on the classification start-up path
  for no gain.
- **An empty directory is a supported state.** No artifact means
  `load_artifact` returns None, every document routes to human review, and the
  vector search arm returns zero rows — degraded, never broken.

`joblib.load` unpickles, i.e. it executes the file's contents. That is only
acceptable because this path is *operator-supplied deployment input* inside the
same trust boundary as the image. **Never point `MODEL_ARTIFACT_PATH` at a
location any tenant or request handler can write to.**

### 3. What the API is allowed to do with the model

The API embeds the **search query** (`app/api/v1/search.py`) so the pgvector arm
has something to rank against, resolving the encoder through the same manifest
the workers use so query and corpus vectors always come from one model. That is
not classification — no label is written in a request handler — so invariant #2
is untouched. When no artifact or encoder is available, the query embedding is
`None`, the vector arm returns zero rows, and search stays keyword-only.
