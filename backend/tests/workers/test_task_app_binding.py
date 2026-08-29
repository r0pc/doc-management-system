"""Pipeline tasks must be bound to the configured Celery app on import alone.

The API reaches ``app.workers.tasks`` through a function-local import inside
``_enqueue_chain`` and nothing else in that process imports
``app.workers.celery_app``. Under ``celery.shared_task`` the decorators then
bound to Celery's *default* app -- broker unset, so ``.delay()`` dialled the
``amqp://localhost:5672`` fallback and raised ECONNREFUSED. Upload completion
returned 503 while the worker sat connected and healthy, because the worker
starts via ``-A app.workers.celery_app`` and therefore had the app.

This has to run in a SUBPROCESS: the moment any test imports celery_app, the
app becomes current and the binding looks correct for the rest of the session,
which is exactly why the in-process suite never caught it.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[2]

# Import ONLY the tasks module, the way the API does. No celery_app import.
PROBE = """
import json
from app.workers.tasks import process_upload_chain
from app.config import Settings
conf = process_upload_chain.app.conf
print(json.dumps({
    "broker": conf.broker_url,
    "settings_redis_url": Settings().redis_url,
    "task_name": process_upload_chain.name,
}))
"""


def _run_probe() -> dict[str, str | None]:
    import json

    result = subprocess.run(  # noqa: S603 - fixed argv, this interpreter, literal PROBE
        [sys.executable, "-c", PROBE],
        cwd=BACKEND_ROOT,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert result.returncode == 0, f"probe failed:\n{result.stderr[-2000:]}"
    return json.loads(result.stdout.strip().splitlines()[-1])


def test_task_is_bound_to_a_configured_broker_without_importing_celery_app() -> None:
    probe = _run_probe()
    assert probe["broker"], (
        "process_upload_chain bound to a Celery app with no broker configured. "
        "Importing app.workers.tasks alone must yield tasks bound to the "
        "configured app, or every API-side .delay() falls back to amqp://localhost."
    )


def test_bound_broker_is_the_redis_url_from_settings() -> None:
    """Compared INSIDE the subprocess: this suite runs with env_file disabled
    for hermeticity, so an in-test Settings() would not see the same .env the
    subprocess does. The invariant is that the task's broker matches the
    settings of the process the task lives in."""
    probe = _run_probe()
    assert probe["broker"] == probe["settings_redis_url"]


def test_task_registered_under_its_module_path() -> None:
    """The worker resolves by name; a rebind must not rename the task."""
    probe = _run_probe()
    assert probe["task_name"] == "app.workers.tasks.process_upload_chain"
