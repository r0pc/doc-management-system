# docmgmt-backend

FastAPI + Celery backend for the Secure Document Management System. One codebase, one image; the API and all workers import the same `app/` package.

---

## Interpreter & Environment

- **Host Interpreter**: CPython 3.14.4 (Windows 11). Virtual environment at `backend/.venv`.
- **Container Environment**: `python:3.12-slim` (see [`Dockerfile`](Dockerfile)).
- **Database Port**: Published on host port **55432** to avoid collision with native Windows PostgreSQL services.
- **Worker Configuration**: Local dev workers use `--pool=solo`; production deployment uses prefork/gevent pools.

---

## Commands

```bash
# Environment setup
source .venv/Scripts/activate          # git-bash
pip install -e ".[parsers,dev]"

# Migrations
alembic upgrade head                   # apply all schema & security migrations
alembic downgrade base                 # test reversible DDL
alembic upgrade head

# Quality Gates
ruff check . && ruff format --check .  # linting & formatting
mypy app                               # strict typecheck (61 source files clean)
pytest -q                              # hermetic test suite (466 passed)
pytest -m integration -v               # live infra integration suite (6 passed)

# Local Development Servers
uvicorn app.main:app --reload --port 8000
celery -A app.workers.celery_app worker -Q default -l info --pool=solo
celery -A app.workers.celery_app worker -Q ocr -l info --pool=solo
```

---

## Package Layout

```
backend/app/
  api/
    deps.py              # Tenant-scoped session factories, auth verifiers, audit helper
    v1/
      uploads.py         # Presigned upload intent (S2), completion, blob promotion
      documents.py       # Document views, range-streaming content (S5), reclassify
      review.py          # Review queue listing, human resolution (S4), check_monotonic
      search.py          # Hybrid keyword + vector search with pre-filtering (Invariants #27, #28)
      audit.py           # Read-only audit log inspection (Invariant #24)
      admin.py           # Taxonomy, prototype trainer, and detector rules CRUD/preview
      events.py          # 501 SSE placeholder
      dev_storage.py     # Local storage presigned URL dispatcher
      errors.py          # Uniform RFC 7807 problem details & cross-tenant 404 parity (#31)
  classification/
    pipeline.py          # Stage coordination: rules -> prototypes -> ml -> review queue
    rules/
      base.py            # Base recognizer interface & context-scoring window
      recognizers.py     # Builtin Luhn card, CNIC province, IBAN, Passport recognizers
      configured.py      # Configurable tenant recognizers with structural validators (#10)
      validators.py      # Structural validator registry (luhn, mod97, entropy, prefix_charset, checksum_suffix)
      safety.py          # ReDoS static analysis & regex canary execution guard
    ml/
      loader.py          # CalibratedClassifierCV v1 artifact contract loader
      prototypes.py      # Few-shot centroid vector computation & cosine similarity
  db/
    base.py              # DeclarativeBase with strict naming conventions
    models.py            # 16 spec §6 SQLAlchemy models (deferred FK #22, non-PK rank #23)
    session.py           # AsyncEngine & tenant session opener with RLS GUC binding
    pagination.py        # Keyset cursor pagination with arbitrary column sort (#32)
  domain/
    policy.py            # Pure two-axis access control & monotonic aggregation (#8, #25)
    taxonomy.py          # Entity-to-rank mappings & CNIC threshold constants
    models.py            # Frozen value objects, Action enum, UserCtx, Finding
  extraction/
    registry.py          # Handler resolution by sniffed MIME
    sniff.py             # Magic-bytes sniffing via puremagic (#19)
    pdf.py               # PyMuPDF extractor with OCR routing fallback
    docx.py              # Structural python-docx parser
    xlsx.py              # Structural openpyxl parser
    keywords.py          # spaCy / fallback TF-IDF keyword extractor
  search/
    hybrid.py            # Reciprocal Rank Fusion (k=60) with pre-ranking visibility filter
  security/
    auth.py              # Cached OIDC JWKS verifier (#7) + dev JWT shim
    permissions.py       # Role -> Action permission matrix (PREVIEW != DOWNLOAD #18)
    audit.py             # Same-transaction audit write contracts (#30)
  storage/
    base.py              # Storage protocol & PrimaryBlobGuard immutability mixin (#16)
    local.py             # HMAC-signed dev storage backend
    s3.py                # S3 / MinIO production storage backend
    keys.py              # Deterministic storage key generator
  workers/
    celery_app.py        # Celery app initialization with queue routing (default vs ocr)
    tasks.py             # 6-stage canvas: scan -> extract -> keywords -> embed -> classify -> index
    jobs.py              # Transactional processing_jobs state journal (#4)
    scanning.py          # ClamAV INSTREAM socket client
```

---

## Configuration Reference (`app/config.py`)

| Setting | Type | Default | Description |
|---|---|---|---|
| `env` | `"dev" \| "prod"` | `"dev"` | Environment mode; prod enforces `scan_enabled=true` at startup |
| `database_url` | `str` | `postgresql+psycopg://docmgmt:docmgmt@localhost:55432/docmgmt` | PostgreSQL 16 connection URL |
| `redis_url` | `str` | `redis://localhost:6379/0` | Celery Redis broker URL |
| `storage_backend` | `"local" \| "minio"` | `"local"` | Storage driver backend |
| `minio_endpoint` | `str` | `localhost:9000` | MinIO endpoint |
| `minio_bucket_prefix` | `str` | `"docs-"` | Prefix for quarantine, primary, derived buckets |
| `scan_enabled` | `bool` | `false` | ClamAV scanning toggle (dev default `false`; mandatory `true` in prod) |
| `upload_max_bytes` | `int` | `104857600` | Maximum upload size in bytes (100 MiB default) |
| `presign_ttl_seconds`| `int` | `90` | Presigned URL expiration (clamped to 60–120s) |
| `dev_jwt_secret` | `str` | `...` | Secret for dev JWT verification |
| `upload_presign_ttl_seconds` | `int` | `900` | Presigned upload URL expiration (clamped to 60–900s) |
| `docmgmt_local_storage_root` | `str` | `"var/storage"` | Root path for local storage when `STORAGE_BACKEND=local` |

### Infrastructure
- **`docker/clamav/clamd.conf`**: Custom ClamAV configuration mounted to increase `StreamMaxLength` (100M) and `MaxScanSize` (150M) to match application upload limits.