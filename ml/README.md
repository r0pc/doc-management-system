# ml/ — Offline & Kaggle ML Training Toolkit

Toolkit for synthetic corpus generation, double-gated dataset export, and calibrated classifier training for the Secure Document Management System.

---

## Security & Privacy Controls (Non-Negotiable)

1. **Zero Real Personal Data in Fixtures**: All synthetic entities (CNIC, IBAN, Passport, Credit Card) are generated via `Faker('en_PK')` with cryptographically valid checksums (Luhn, CNIC province prefix).
2. **Strict Airgap & Self-Hosting**: Document text must never leave the deployment. Kaggle is treated as an untrusted third-party environment.
3. **Double-Gated Real Text Export**: Exporting real document text requires **both** the CLI flag `--allow-real-text <path>` **and** the environment variable `DMS_EXPORT_REAL_TEXT_CONFIRM=yes`. If either is missing, export aborts with exit code 2.
4. **Offline Evaluation Separation**: Training scripts strictly segregate synthetic training sets from the 150–200 held-out evaluation set (Invariant #13). Per-class recall on highest security label is tracked near 1.0 (Invariant #14).

---

## Toolkit Structure

| Module / Script | Purpose |
|---|---|
| `entities.py` | Canonical synthetic entity definitions & regex specs matching `domain/taxonomy.py` |
| `templates.py` | 7 document skeleton generators with sensitive label-phrase stripping |
| `generate_synthetic_corpus.py` | Multi-format generator rendering synthetic `.pdf`, `.docx`, `.xlsx` files + `manifest.csv` |
| `export_training_data.py` | Hard-gated dataset exporter converting manifest into `dataset.csv` |
| `train_classifier.py` | Local & remote training script building calibrated `CalibratedClassifierCV` models |
| `train_template.ipynb` | Kaggle notebook template for GPU-accelerated embedding and logistic regression |
| `artifact_contract.md` | Schema v1 contract governing `model.joblib` artifact verification in the backend |
| `tests/` | Hermetic unit tests verifying corpus generation, entity validity, and export safety |

---

## Local Verification & Testing

```bash
cd ml
../backend/.venv/Scripts/python.exe -m pytest tests -q   # 21 hermetic tests passed
../backend/.venv/Scripts/python.exe -m ruff check .      # code formatting & linting
```
