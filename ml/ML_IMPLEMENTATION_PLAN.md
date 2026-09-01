# ML Implementation & Few-Shot Prototype Plan

**Target Model**: `BAAI/bge-small-en-v1.5` (384-dimensional dense sentence embeddings)  
**Target Classifier**: `CalibratedClassifierCV(LogisticRegression(class_weight="balanced"))`  
**Artifact Path**: `backend/var/models/model.joblib`  
**Governing Authority**: `AGENTS.md` and `ml/artifact_contract.md`

---

## 1. Non-Negotiable Invariants to Enforce

1. **Self-Hosting (Strict Hard Requirement)**: Model inference must run locally on CPU/Docker without calling external or hosted APIs.
2. **Embed Once (Invariant #6)**: Compute embeddings once during ingestion and reuse the exact same vector for both classification and `pgvector` hybrid search.
3. **Calibrated Probabilities (Invariant #11)**: ML predictions require calibrated probabilities. Cascade routing: ML $\ge 0.85$, LLM $\ge 0.75$, else route to human review.
4. **No Single Accuracy Metric (Invariant #14)**: Always evaluate and report per-class recall, with `restricted_recall` isolated.
5. **Multi-Tenant Isolation (Invariant #26)**: Custom user categories and prototype vectors must be strictly isolated by `tenant_id` via Row-Level Security (RLS).

---

## 2. Phase 1: Model Training on Kaggle

### 1.1 Dataset Generation
Run locally or inside the Kaggle notebook:
```bash
python ml/generate_synthetic_corpus.py --n 3000 --out dataset.csv
```

### 1.2 Kaggle Training Execution
In a Kaggle Notebook (CPU or T4 GPU):
```python
# Cell 1: Install dependencies
!pip install -q sentence-transformers scikit-learn joblib pandas numpy

# Cell 2: Run training script
!python train_classifier.py --dataset dataset.csv --out-dir ./output --test-size 0.2 --random-state 42
```

### 1.3 Validation of Output Artifacts
Verify that `./output/model.joblib` and `./output/metrics.json` were created:
* `metrics.json` must contain per-class recall for `doc_type` and `security_level`.
* `manifest["dim"]` must be `384`.
* `manifest["embedding_model_id"]` must be `"BAAI/bge-small-en-v1.5"`.

### 1.4 Artifact Placement
Download `model.joblib` and place it in the repository:
```bash
mkdir -p backend/var/models
cp model.joblib backend/var/models/model.joblib
```

---

## 3. Phase 2: Live ML Inference Wiring in Backend

### 3.1 Worker Dependencies
In `backend/pyproject.toml` (or worker Dockerfile), ensure dependencies exist:
```toml
dependencies = [
    # ... existing ...
    "sentence-transformers>=2.2.0",
    "scikit-learn>=1.4.0",
    "joblib>=1.3.0",
    "torch --index-url https://download.pytorch.org/whl/cpu",
]
```

### 3.2 Wire `_predict_with_artifact` in `backend/app/classification/ml/loader.py`
Replace the placeholder raise in `_predict_with_artifact`:

```python
import numpy as np
from sentence_transformers import SentenceTransformer

# Cached model instance
_EMBED_MODEL: SentenceTransformer | None = None

def _get_embed_model(model_id: str) -> SentenceTransformer:
    global _EMBED_MODEL
    if _EMBED_MODEL is None:
        _EMBED_MODEL = SentenceTransformer(model_id)
    return _EMBED_MODEL

def _predict_with_artifact(artifact: MlArtifact, text: str) -> tuple[str, float]:
    """Encode text and predict doc_type using the calibrated LogisticRegression head."""
    model_id = artifact.manifest.embedding_model_id
    embedder = _get_embed_model(model_id)
    
    # 1. Compute normalized dense embedding (first 4000 chars)
    embedding = embedder.encode(text[:4000], show_progress_bar=False, normalize_embeddings=True)
    features = np.asarray([embedding])
    
    # 2. Run doc_type head
    doc_type_bundle = artifact.payload["models"]["doc_type"]
    clf = doc_type_bundle["model"]
    encoder = doc_type_bundle["label_encoder"]
    
    probs = clf.predict_proba(features)[0]
    top_idx = int(np.argmax(probs))
    top_prob = float(probs[top_idx])
    predicted_label = str(encoder.inverse_transform([top_idx])[0])
    
    return predicted_label, top_prob
```

---

## 4. Phase 3: Ingestion Pipeline Embeddings & Vector Search

### 4.1 Persist Embeddings during Worker Ingestion
In `backend/app/workers/tasks.py`, ensure the text extraction stage computes and stores `document_text.embedding`:

```python
# Inside pipeline task execution
embedding = _get_embed_model("BAAI/bge-small-en-v1.5").encode(text[:4000], normalize_embeddings=True)

# Store in database
session.execute(
    update(DocumentText)
    .where(DocumentText.version_id == version_id)
    .values(embedding=embedding.tolist())
)
```

### 4.2 Activate Vector Arm in `backend/app/search/hybrid.py`
Replace `.where(false())` in `compose_vector_subquery` with cosine distance ranking:

```python
def compose_vector_subquery(query_embedding: list[float], limit: int = 50):
    return (
        select(
            DocumentText.version_id,
            (1 - DocumentText.embedding.cosine_distance(query_embedding)).label("score")
        )
        .order_by(DocumentText.embedding.cosine_distance(query_embedding).asc())
        .limit(limit)
    )
```

---

## 5. Phase 4: Few-Shot Dynamic Category Prototypes [IMPLEMENTED]

*(Implemented in Phase 2 via migration `0006_admin_extensibility.py`, `backend/app/classification/ml/prototypes.py`, `backend/app/api/v1/admin.py`, and `backend/app/classification/pipeline.py`)*

### 5.1 Database Migration (`alembic/versions/0006_admin_extensibility.py`)
```python
"""Add tenant-specific custom doc_types, prototype centroid vectors, and detector rules."""

def upgrade() -> None:
    # 1. Add tenant_id to doc_types (nullable for global types)
    op.add_column("doc_types", sa.Column("tenant_id", sa.UUID(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True))
    
    # 2. Create prototypes table
    op.execute("""
    CREATE TABLE doc_type_prototypes (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
        doc_type_id UUID NOT NULL REFERENCES doc_types(id) ON DELETE CASCADE,
        centroid_vector vector(384) NOT NULL,
        sample_count INT NOT NULL CHECK (sample_count >= 5),
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        CONSTRAINT uq_tenant_doc_type UNIQUE (tenant_id, doc_type_id)
    );
    
    CREATE INDEX idx_prototypes_vector ON doc_type_prototypes 
    USING hnsw (centroid_vector vector_cosine_ops);
    
    ALTER TABLE doc_type_prototypes ENABLE ROW LEVEL SECURITY;
    ALTER TABLE doc_type_prototypes FORCE ROW LEVEL SECURITY;
    
    CREATE POLICY tenant_isolation ON doc_type_prototypes
    FOR ALL TO docmgmt_app
    USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);
    """)
```

### 5.2 Centroid Computation Engine (`backend/app/classification/ml/prototypes.py`)
```python
import numpy as np
import uuid
from sqlalchemy.orm import Session
from app.db.models import DocumentText, Document, DocTypePrototype

def train_category_prototype(session: Session, tenant_id: uuid.UUID, doc_type_id: uuid.UUID, doc_ids: list[uuid.UUID]):
    rows = (
        session.query(DocumentText.embedding)
        .join(Document, Document.id == DocumentText.document_id)
        .filter(Document.tenant_id == tenant_id, Document.id.in_(doc_ids), DocumentText.embedding.isnot(None))
        .all()
    )
    if len(rows) < 5:
        raise ValueError(f"Need at least 5 processed sample documents (received {len(rows)})")
        
    vectors = np.array([r.embedding for r in rows], dtype=np.float32)
    mean_vec = np.mean(vectors, axis=0)
    norm = np.linalg.norm(mean_vec)
    centroid = (mean_vec / norm).tolist() if norm > 0 else mean_vec.tolist()
    
    # Upsert prototype
    proto = session.query(DocTypePrototype).filter_by(tenant_id=tenant_id, doc_type_id=doc_type_id).first()
    if proto:
        proto.centroid_vector = centroid
        proto.sample_count = len(rows)
    else:
        proto = DocTypePrototype(tenant_id=tenant_id, doc_type_id=doc_type_id, centroid_vector=centroid, sample_count=len(rows))
        session.add(proto)
    session.commit()
    return proto
```

### 5.3 Classification Cascade Hook (`backend/app/classification/pipeline.py`)
Before routing to the global ML model or human review, check against tenant prototypes:
```python
def match_custom_prototypes(session: Session, tenant_id: uuid.UUID, doc_vector: list[float]) -> tuple[uuid.UUID, float] | None:
    match = (
        session.query(
            DocTypePrototype.doc_type_id,
            (1 - DocTypePrototype.centroid_vector.cosine_distance(doc_vector)).label("similarity")
        )
        .filter(DocTypePrototype.tenant_id == tenant_id)
        .order_by("similarity DESC")
        .first()
    )
    if match and match.similarity >= 0.85:  # Invariant #11 threshold
        return match.doc_type_id, float(match.similarity)
    return None
```

---

## 6. Verification and Quality Gates

Run all quality checks after executing each phase:
```bash
# Backend Quality Gates
cd backend
ruff check .
mypy app
pytest -q

# ML Unit Tests
cd ../ml
pytest tests -q
```
