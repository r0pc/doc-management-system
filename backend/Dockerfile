# One image, three uses: api / worker / worker-ocr (compose overrides the
# entrypoint/command per service). No worker-local copy of app code exists.
FROM python:3.12-slim

WORKDIR /srv/app

# Dependency layer first for build caching. The project wheel itself ships no
# modules (packages = []); `app` is imported from WORKDIR, not site-packages.
COPY pyproject.toml ./
RUN pip install --no-cache-dir ".[parsers]"

COPY alembic.ini ./
COPY alembic ./alembic
COPY app ./app
COPY scripts ./scripts

RUN adduser --disabled-password --no-create-home appuser && \
    chown -R appuser:appuser /srv/app

USER appuser

# CMD args are appended to ENTRYPOINT, so `docker run <image> --port 8000`
# works; workers swap the entrypoint entirely in docker-compose.yml.
ENTRYPOINT ["./scripts/entrypoint-api.sh", "uvicorn", "app.main:app", "--host", "0.0.0.0"]
CMD ["--port", "8000"]
