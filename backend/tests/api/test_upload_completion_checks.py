"""Completion must verify the object landed and is the size that was declared.

Invariant #1 keeps the API off the bytes, so these are metadata checks only:
existence and length, never a read.
"""

from __future__ import annotations

import io
from typing import Any
from uuid import UUID

import pytest
from starlette.status import HTTP_409_CONFLICT, HTTP_413_CONTENT_TOO_LARGE

from app.storage.keys import quarantine_key
from tests.api.conftest import TENANT_A, install_worker_fake
from tests.api.test_uploads import patch_complete_persistence

DOC_ID = UUID(int=0xC0FFEE)


@pytest.fixture
def _setup_completion(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}
    patch_complete_persistence(monkeypatch, captured)
    install_worker_fake(monkeypatch)


def test_complete_rejects_when_no_object_was_ever_put(client: Any, _setup_completion: None) -> None:
    response = client.post(f"/v1/uploads/{DOC_ID}/complete", json={"size_bytes": 10})
    assert response.status_code == HTTP_409_CONFLICT
    assert "did not arrive" in response.json()["detail"]


def test_complete_rejects_size_over_cap(
    client: Any, monkeypatch: pytest.MonkeyPatch, _setup_completion: None
) -> None:
    from app.storage.base import ObjectStat

    monkeypatch.setattr(
        "app.storage.local.LocalStorage.stat", lambda self, key: ObjectStat(size_bytes=2_000_000)
    )
    response = client.post(f"/v1/uploads/{DOC_ID}/complete", json={"size_bytes": 2_000_000})
    assert response.status_code == HTTP_413_CONTENT_TOO_LARGE
    assert "upload cap" in response.json()["detail"]


def test_complete_rejects_a_size_mismatch(
    client: Any, blob_storage: Any, _setup_completion: None
) -> None:
    key = quarantine_key(TENANT_A, DOC_ID)
    blob_storage.put(key, io.BytesIO(b"x" * 10), content_type="application/pdf")
    response = client.post(f"/v1/uploads/{DOC_ID}/complete", json={"size_bytes": 999})
    assert response.status_code == HTTP_409_CONFLICT
    assert "size" in response.json()["detail"]


def test_complete_accepts_a_matching_object(
    client: Any, blob_storage: Any, _setup_completion: None
) -> None:
    key = quarantine_key(TENANT_A, DOC_ID)
    blob_storage.put(key, io.BytesIO(b"x" * 10), content_type="application/pdf")
    response = client.post(f"/v1/uploads/{DOC_ID}/complete", json={"size_bytes": 10})
    assert response.status_code == 200
    assert response.json()["status"] == "processing"


def test_complete_never_reads_the_body(
    client: Any, blob_storage: Any, _setup_completion: None
) -> None:
    """#1: the API signs and records intent; it does not touch the bytes."""
    key = quarantine_key(TENANT_A, DOC_ID)
    blob_storage.put(key, io.BytesIO(b"x" * 10), content_type="application/pdf")
    client.post(f"/v1/uploads/{DOC_ID}/complete", json={"size_bytes": 10})
    assert blob_storage.open_calls == [], "completion read the object body (#1 violation)"
