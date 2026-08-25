# docmgmt-backend

FastAPI + Celery backend for the Secure Document Management System. One codebase, one image; the API and all workers import the same `app/` package.

## Interpreter / environment

- **Chosen interpreter: host CPython 3.14.4** (`C:\Python314\python.exe`). `py -0p` listed **only** 3.14 — no 3.11–3.13 was available via the `py` launcher, so `.venv` was created with `python -m venv .venv` from the host interpreter.
- Venv location: `backend/.venv` (gitignored). Activate in git-bash: `source .venv/Scripts/activate`.
- Installed extras: core + `parsers` + `dev`. All parser wheels resolved on 3.14 (pymupdf 1.28.2 ships cp314 wheels) — nothing skipped.
- The Docker image uses `python:3.12-slim`, independent of the host venv.
- `[build-system]` uses setuptools solely so `pip install ".[parsers,dev]"` can resolve dependency sets; the wheel ships zero modules (`packages = []`) because `app` is imported from the working directory, never site-packages.

## Tooling

```bash
python -m ruff check .        # lint
python -m ruff format .       # format (line length 100, double quotes)
python -m mypy app            # strict type check
python -m pytest -q           # hermetic tests; integration marker excluded by default
alembic revision --autogenerate -m "..."   # no versions exist until Wave 2.A
```

## Layout

```
app/
  __init__.py
  config.py          # frozen pydantic-settings; validate_runtime() fail-closed guard
  main.py            # app factory, GET /healthz
  deps.py            # request dependencies (placeholder, later waves)
  api/v1/            # routers (empty, later waves)
  classification/    # rules/, ml/ (llm deliberately omitted this wave)
  db/base.py         # DeclarativeBase + naming_convention
  domain/            # policy/taxonomy/models (later waves)
  extraction/        # pdf/docx/xlsx/ocr parsers (later waves)
  search/            # hybrid search (later waves)
  security/          # auth/permissions/audit (later waves)
  storage/           # local/minio backends (later waves)
  workers/
    celery_app.py    # Celery("docmgmt"); default + ocr queues, task_routes
    tasks.py         # pipeline stages (Wave 3)
alembic/
  env.py             # URL injected from Settings.sync_db_url, never hardcoded
  script.py.mako
  versions/          # empty by design until Wave 2.A
tests/
  test_health.py     # /healthz smoke test (runs without any infra)
Dockerfile           # python:3.12-slim; ENTRYPOINT uvicorn, CMD args appended
pyproject.toml
```

## Configuration reference (`app/config.py`)

| Field | Type | Default | Notes |
|---|---|---|---|
| `env` | `"dev" \| "prod"` | `"dev"` | prod requires `scan_enabled=true` or startup fails |
| `database_url` | str | `postgresql+psycopg://docmgmt:docmgmt@localhost:5432/docmgmt` | psycopg3 dialect serves sync + async |
| `sync_db_url` | property | derived | normalises async dialects to `+psycopg` for Alembic/Celery engines |
| `redis_url` | str | `redis://localhost:6379/0` | Celery broker |
| `storage_backend` | `"local" \| "minio"` | `"local"` | filesystem backend keeps tests hermetic |
| `minio_endpoint` | str | `localhost:9000` | self-hosted only |
| `minio_access_key` | str | `minioadmin` | compose/dev default |
| `minio_secret_key` | str | `minioadmin` | change before any real deployment |
| `minio_secure` | bool | `false` | TLS toggle |
| `minio_bucket_prefix` | str | `"docs-"` | buckets: `docs-quarantine/docs-primary/docs-derived` |
| `scan_enabled` | bool | `false` | ClamAV scanning; mandatory true in prod |
| `dev_jwt_secret` | str | `dev-only-secret-change-me` | dev shim; OIDC replaces it later |
| `oidc_issuer` | str \| None | `None` | Keycloak issuer URL |
| `oidc_audience` | str \| None | `None` | expected token audience |
| `upload_max_bytes` | int | `104857600` | 100 MiB upload cap |
| `presign_ttl_seconds` | int | `90` | clamped to 60..120 by validator |

Settings read `.env` (cwd-relative), no env prefix, unknown keys ignored. Frozen after construction.
