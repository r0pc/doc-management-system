#!/bin/sh
# Shared bootstrap for the api / worker / worker-ocr containers (one image,
# three entrypoints). Waits for PostgreSQL, applies migrations, then execs
# the service command so PID 1 stays the real server and signals propagate.
#
# Pipeline invariant #4: every stage's state lives in processing_jobs, which
# requires the schema to exist before any process touches the database.
set -eu

python - <<'PY'
import os
import sys
import time

import psycopg

url = os.environ.get("DATABASE_URL", "").replace("+psycopg", "")
if not url:
    print("entrypoint: DATABASE_URL is not set", file=sys.stderr)
    sys.exit(1)

tries = int(os.environ.get("WAIT_FOR_DB_TRIES", "30"))
last_error = None
for _ in range(tries):
    try:
        psycopg.connect(url, connect_timeout=3).close()
        sys.exit(0)
    except Exception as exc:  # retry any connect failure until the deadline
        last_error = exc
        time.sleep(1)

print(f"entrypoint: postgres unreachable after {tries} attempts: {last_error}",
      file=sys.stderr)
sys.exit(1)
PY

exec "$@"
