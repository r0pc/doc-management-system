# One image, three uses: api / worker / worker-ocr (compose overrides the
# entrypoint/command per service). No worker-local copy of app code exists.
FROM python:3.12-slim

WORKDIR /srv/app

# curl is required by the compose healthchecks.
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

# Dependency layer first for build caching. The project wheel itself ships no
# modules (packages = []); `app` is imported from WORKDIR, not site-packages.
COPY pyproject.toml ./
RUN pip install --no-cache-dir ".[parsers]"

COPY alembic.ini ./
COPY alembic ./alembic
COPY app ./app

# CMD args are appended to ENTRYPOINT, so `docker run <image> --port 8000`
# works; workers swap the entrypoint entirely in docker-compose.yml.
ENTRYPOINT ["uvicorn", "app.main:app", "--host", "0.0.0.0"]
CMD ["--port", "8000"]
