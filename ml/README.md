# ml/ — Kaggle training toolkit

Synthetic corpus generation and Kaggle-side training for the Secure DMS classifiers
(security level + document type). Nothing here touches real data by default.

## Security rails (repeated from AGENTS.md — non-negotiable)

- **No real personal data anywhere.** All fixtures/corpus use `Faker('en_PK')` synthetic values.
- **Self-hosting invariant:** document text must not leave the deployment. Kaggle is a
  third-party service. Exporting *real* document text requires BOTH `--allow-real-text <path>`
  AND env `DMS_EXPORT_REAL_TEXT_CONFIRM=yes`; either alone refuses with exit code 2.
- Never log document text or matched identifier values.

## Layout

| File | Purpose |
|---|---|
| `entities.py` | canonical synthetic entity formats + spec §3.7 SPECS (single source) |
| `templates.py` | 7 hand-written skeleton templates + label-phrase stripper |
| `generate_synthetic_corpus.py` | CLI: renders .docx/.xlsx/.pdf per record + manifests |
| `export_training_data.py` | CLI: dataset.csv exporter with the double-gated real-text mode |
| `train_classifier.py` | trainer (heavy imports lazy; run where torch/sklearn exist) |
| `train_template.ipynb` | Kaggle notebook mirroring the trainer steps |
| `requirements-kaggle.txt` | documented Kaggle dependencies |
| `artifact_contract.md` | schema v1 contract consumed by the Wave 2.C backend loader |

## Kaggle workflow

1. **Generate locally** (synthetic only):
   ```bash
   cd ml
   ../backend/.venv/Scripts/python.exe generate_synthetic_corpus.py --count 500 --out corpus --seed 42
   ../backend/.venv/Scripts/python.exe export_training_data.py corpus/manifest.csv --out dataset.csv
   ```
2. **Upload** `dataset.csv` to Kaggle as a private Dataset (*Add Input*).
3. **Run** `train_template.ipynb` on Kaggle (first cell installs `requirements-kaggle.txt`;
   embeddings run on the Kaggle VM with self-hosted model weights — no hosted LLM/embedding API).
4. **Download** `model.joblib` (+ `metrics.json`) from the notebook output.
5. **Drop into the backend models dir** — the Wave 2.C classification/ml loader consumes it per
   `artifact_contract.md` (sklearn major.minor match, dim 384, labels ⊆ taxonomy).

## Local checks

```bash
cd ml
../backend/.venv/Scripts/python.exe -m pytest tests -q
../backend/.venv/Scripts/python.exe -m ruff check .
```

Tests need no network and no heavy ML stack; they run entirely on the local venv
(faker / python-docx / openpyxl / fpdf2).
