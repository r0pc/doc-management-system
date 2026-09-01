# Troubleshooting

Failures that look like bugs but are the system refusing to run misconfigured.
Each one is deliberate: it fails at startup with an explanation rather than
degrading into a per-request error that is far harder to diagnose.

## The API refuses to start, mentioning `ENV`

`ENV` defaults to `prod`, and a production process must prove it was configured
(see the Production block in `.env.example`). Without a root `.env` there is
nothing to set `ENV=dev`, so startup is refused by design rather than silently
running a dev-shaped process under production defaults.

Fix: `cp .env.example .env` at the repo root.

## Every database request fails on Windows

`--reload` is not optional there. psycopg's async mode cannot run on
`ProactorEventLoop`, and uvicorn selects a compatible loop only when
`use_subprocess` is set (`--reload`, or `--workers > 1`). Without it the server
starts and then fails every database request.

Startup now refuses outright with that explanation instead of degrading to a 500
per request. Linux, macOS and the Docker images are unaffected.

## Settings look ignored / `.env` seems unread

`.env` lives at the **repo root** and is found from there no matter which
directory you launch from — `app/config.py` anchors the lookup on its own
location, not the process CWD. A `backend/.env`, if present, overrides it.

## A route 404s or 405s that plainly exists in the source

The running container is stale. Code is baked into the image, not bind-mounted,
so backend edits do not reach a running stack until it is rebuilt.

A POST to a route the image lacks is especially misleading: it falls through to
`GET /v1/documents/{document_id}`, binds `document_id` to the literal path
segment, and returns **405 Method Not Allowed** — which does not read as a
deployment problem at all.

```bash
docker compose build api worker worker-ocr && docker compose up -d
```

Rebuild the workers too, not just the API. A new Celery task in an API-only
rebuild returns a cheerful `200` while the job sits in the queue forever,
because no worker knows the task exists.

`frontend/e2e/deployment.spec.ts` checks this automatically: it reads every
`/v1/...` path out of the client source and asserts each one is live on the
running API.

## Integration tests fail to reach ClamAV

Run them from the host with the scanner's hostname pointed at the published
port:

```bash
CLAMAV_HOST=localhost pytest -m integration -v
```
