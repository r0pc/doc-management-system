# One image, three uses: api / worker / worker-ocr (compose overrides the
# entrypoint/command per service). No worker-local copy of app code exists.
FROM python:3.12-slim

WORKDIR /srv/app

# Dependency layer first for build caching. The project wheel itself ships no
# modules (packages = []); `app` is imported from WORKDIR, not site-packages.
COPY pyproject.toml ./

# torch first, pinned to the CPU wheel index: the default PyPI wheel drags in
# the CUDA runtime (multiple GB) that this CPU-only deployment can never use.
# Installing it up front means the ".[ml]" resolve below finds torch satisfied
# and never reaches for the GPU build.
RUN pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu torch \
    && pip install --no-cache-dir ".[parsers,ml]"

# --- model weights: local, baked at BUILD time, never fetched at inference ---
#
# Self-hosting is a hard requirement: document text may not leave the
# deployment, and SentenceTransformer(model_id) would otherwise reach out to
# huggingface.co the first time a worker classifies anything. So the encoder is
# materialised HERE, during the image build (a supply-chain step, like pip),
# into a directory inside the image; at runtime HF_HUB_OFFLINE/TRANSFORMERS_
# OFFLINE make any attempted download a hard error instead of a silent egress.
#
# Air-gapped builds: pre-populate this directory from an internal mirror and
# skip the RUN below, or mount a host cache over /opt/hf-cache at runtime.
ENV HF_HOME=/opt/hf-cache \
    SENTENCE_TRANSFORMERS_HOME=/opt/hf-cache \
    HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1
RUN HF_HUB_OFFLINE=0 TRANSFORMERS_OFFLINE=0 python -c \
    "from sentence_transformers import SentenceTransformer; \
     SentenceTransformer('BAAI/bge-small-en-v1.5')"

COPY alembic.ini ./
COPY alembic ./alembic
COPY app ./app
COPY scripts ./scripts

# The TRAINED CLASSIFIER (model.joblib) is deliberately NOT copied in. It is
# gitignored, it is not redistributable with the image, and AGENTS.md forbids
# committing model weights; docker-compose mounts backend/var/models read-only
# and points MODEL_ARTIFACT_PATH at it instead. An absent artifact is a normal
# state: the loader returns None and every document routes to human review.
RUN adduser --disabled-password --no-create-home appuser && \
    chown -R appuser:appuser /srv/app && \
    chmod -R a+rX /opt/hf-cache

USER appuser

# CMD args are appended to ENTRYPOINT, so `docker run <image> --port 8000`
# works; workers swap the entrypoint entirely in docker-compose.yml.
ENTRYPOINT ["./scripts/entrypoint-api.sh", "uvicorn", "app.main:app", "--host", "0.0.0.0"]
CMD ["--port", "8000"]
