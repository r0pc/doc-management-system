"""The compose mount and the resolved storage root must be the same path.

A mismatch is invisible until runtime: the worker writes the primary blob into
its own container layer and the API 404s every download.
"""

from __future__ import annotations

from pathlib import Path

import yaml

_REPO_ROOT = Path(__file__).resolve().parents[2]
_COMPOSE = _REPO_ROOT / "docker-compose.yml"
_SERVICES = ("api", "worker", "worker-ocr")
_ENV_VAR = "DOCMGMT_LOCAL_STORAGE_ROOT"


def _compose() -> dict:
    return yaml.safe_load(_COMPOSE.read_text(encoding="utf-8"))


def test_storage_volume_mount_matches_pinned_root() -> None:
    services = _compose()["services"]
    for name in _SERVICES:
        service = services[name]
        mounts = [v for v in service["volumes"] if v.startswith("storage-data:")]
        assert len(mounts) == 1, f"{name} must mount storage-data exactly once"
        mount_path = mounts[0].split(":", 1)[1]
        pinned = service["environment"][_ENV_VAR]
        assert pinned == mount_path, (
            f"{name}: {_ENV_VAR}={pinned!r} does not match volume mount {mount_path!r}"
        )


def test_every_storage_service_pins_the_root_explicitly() -> None:
    services = _compose()["services"]
    for name in _SERVICES:
        assert _ENV_VAR in services[name]["environment"], (
            f"{name} must pin {_ENV_VAR}; relying on resolve_storage_root() "
            "inside the container resolves to /srv/var/storage, not the volume"
        )
