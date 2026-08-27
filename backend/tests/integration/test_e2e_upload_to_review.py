# ruff: noqa: S105, E501
"""Wave 5A end-to-end system verification suite.

Exercises the complete lifecycle against real PostgreSQL and ClamAV:
- S0: Database migrated to head with seed data
- S1: Minted dev JWTs for multiple tenants/clearances
- S2: Upload intent -> quarantine storage PUT -> upload completion
- S3: Worker pipeline execution (scan -> extract -> keywords -> embed -> classify -> index)
- S4: Human review resolution & lowering under check_monotonic trigger (#8) + audit trail
- S5: Content splitting (Confidential/Restricted streams with Range, Internal redirects)
- S6: Cross-tenant 404 byte-parity (#31)
- S7: EICAR malware rejection against live ClamAV (#4)
"""

from __future__ import annotations

import io
import uuid
from pathlib import Path
from typing import TYPE_CHECKING

import psycopg
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import deps
from app.api.v1.errors import not_found
from app.config import Settings
from app.main import create_app
from app.security.auth import DevJWTVerifier, issue_dev_token
from app.storage.keys import quarantine_key
from app.storage.local import LocalStorage
from app.workers import jobs, tasks
from app.workers.celery_app import celery_app

if TYPE_CHECKING:
    from tests.integration.conftest import DbTarget

pytestmark = [pytest.mark.integration]

DEV_SECRET = "e2e-integration-secret-key-32bytes-long"

# Valid PDF containing >= 20 characters of text so PdfHandler does not trip NeedsOcrError
PDF_PAYLOAD = (
    b"%PDF-1.4\n"
    b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
    b"2 0 obj<</Type/Pages/Count 1/Kids[3 0 R]>>endobj\n"
    b"3 0 obj<</Type/Page/MediaBox[0 0 612 792]/Parent 2 0 R/Resources<<>>/Contents 4 0 R>>endobj\n"
    b"4 0 obj<</Length 63>>stream\n"
    b"BT /F1 12 Tf 72 712 Td (Quarterly Financial Report Q4 Summary Acme Corp) Tj ET\n"
    b"endstream\nendobj\n"
    b"xref\n0 5\n0000000000 65535 f \n0000000009 00000 n \n0000000056 00000 n \n"
    b"0000000111 00000 n \n0000000212 00000 n \ntrailer<</Size 5/Root 1 0 R>>\n"
    b"startxref\n325\n%%EOF\n"
)

# Valid PDF structure containing the standard EICAR test string
EICAR_PAYLOAD = (
    b"%PDF-1.4\n"
    b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
    b"2 0 obj<</Type/Pages/Count 1/Kids[3 0 R]>>endobj\n"
    b"3 0 obj<</Type/Page/MediaBox[0 0 612 792]/Parent 2 0 R/Resources<<>>/Contents 4 0 R>>endobj\n"
    b"4 0 obj<</Length 70>>stream\n"
    b"X5O!P%@AP[4\\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*\n"
    b"endstream\nendobj\n"
    b"xref\n0 5\n0000000000 65535 f \n0000000009 00000 n \n0000000056 00000 n \n"
    b"0000000111 00000 n \n0000000212 00000 n \ntrailer<</Size 5/Root 1 0 R>>\n"
    b"startxref\n332\n%%EOF\n"
)


@pytest.fixture
def e2e_settings(migrated_db: DbTarget, monkeypatch: pytest.MonkeyPatch) -> Settings:
    monkeypatch.setenv("DATABASE_URL", migrated_db.sqlalchemy_url)
    monkeypatch.setenv("DEV_JWT_SECRET", DEV_SECRET)
    monkeypatch.setenv("SCAN_ENABLED", "true")
    monkeypatch.setenv("STORAGE_BACKEND", "local")
    return Settings(
        env="dev",
        database_url=migrated_db.sqlalchemy_url,
        storage_backend="local",
        upload_max_bytes=10_000_000,
        presign_ttl_seconds=90,
        dev_jwt_secret=DEV_SECRET,
        scan_enabled=True,
    )


@pytest.fixture
def e2e_storage(
    tmp_path: Path, e2e_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> LocalStorage:
    storage_root = (tmp_path / "e2e_storage").resolve()
    storage_root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("DOCMGMT_LOCAL_STORAGE_ROOT", str(storage_root))
    monkeypatch.setattr(deps, "DEFAULT_LOCAL_STORAGE_ROOT", storage_root)
    return LocalStorage(
        storage_root,
        signing_secret=e2e_settings.dev_jwt_secret,
        bucket_prefix=e2e_settings.minio_bucket_prefix,
    )


@pytest.fixture
def eager_pipeline(
    e2e_settings: Settings, e2e_storage: LocalStorage, monkeypatch: pytest.MonkeyPatch
) -> None:
    celery_app.conf.task_always_eager = True
    celery_app.conf.task_store_eager_result = True
    celery_app.conf.task_eager_propagates = False

    # Ensure worker singletons match test settings and storage
    monkeypatch.setattr(tasks, "_settings", lambda: e2e_settings)
    monkeypatch.setattr(tasks, "_storage", lambda: e2e_storage)
    monkeypatch.setattr(jobs, "_sync_sessions", None)


@pytest.fixture
def e2e_app(
    e2e_settings: Settings,
    e2e_storage: LocalStorage,
    monkeypatch: pytest.MonkeyPatch,
) -> FastAPI:
    # Reset cached async engine and session factory to target the migrated_db
    monkeypatch.setattr("app.db.session._engine", None)
    monkeypatch.setattr("app.db.session._session_factory", None)
    monkeypatch.setattr("app.api.deps._storage_singleton", e2e_storage)
    monkeypatch.setattr(
        deps, "get_verifier", lambda: DevJWTVerifier(e2e_settings.dev_jwt_secret, env="dev")
    )
    monkeypatch.setattr(deps, "get_settings", lambda: e2e_settings)

    return create_app()


@pytest.fixture
def e2e_client(e2e_app: FastAPI) -> TestClient:
    return TestClient(e2e_app)


def test_full_e2e_upload_to_review_lifecycle(
    migrated_db: DbTarget,
    e2e_settings: Settings,
    e2e_storage: LocalStorage,
    eager_pipeline: None,
    e2e_client: TestClient,
) -> None:
    """Walk full scenarios S0 through S6 in order against real PostgreSQL."""
    # S0 & S1: Seed Tenants, Departments, Users & mint dev tokens
    tenant_1 = uuid.uuid4()
    tenant_2 = uuid.uuid4()
    dept_hq = uuid.uuid4()
    dept_eng = uuid.uuid4()
    dept_t2 = uuid.uuid4()

    with psycopg.connect(migrated_db.libpq_url, autocommit=True) as conn:
        conn.execute("INSERT INTO tenants (id, name) VALUES (%s, 'Acme Corp')", (tenant_1,))
        conn.execute("INSERT INTO tenants (id, name) VALUES (%s, 'Foreign Corp')", (tenant_2,))
        conn.execute(
            "INSERT INTO departments (id, tenant_id, parent_id, name) VALUES (%s, %s, NULL, 'HQ')",
            (dept_hq, tenant_1),
        )
        conn.execute(
            "INSERT INTO departments (id, tenant_id, parent_id, name) VALUES (%s, %s, %s, 'Engineering')",
            (dept_eng, tenant_1, dept_hq),
        )
        conn.execute(
            "INSERT INTO departments (id, tenant_id, parent_id, name) VALUES (%s, %s, NULL, 'General')",
            (dept_t2, tenant_2),
        )

    admin_t1_token = issue_dev_token(
        "dev-admin", tenant_1, dept_hq, "admin", 4, audience="docmgmt-api", secret=DEV_SECRET
    )
    emp_t1_token = issue_dev_token(
        "dev-emp", tenant_1, dept_eng, "employee", 2, audience="docmgmt-api", secret=DEV_SECRET
    )
    outsider_t2_token = issue_dev_token(
        "dev-outsider", tenant_2, dept_t2, "admin", 4, audience="docmgmt-api", secret=DEV_SECRET
    )

    admin_headers = {"Authorization": f"Bearer {admin_t1_token}"}
    emp_headers = {"Authorization": f"Bearer {emp_t1_token}"}
    outsider_headers = {"Authorization": f"Bearer {outsider_t2_token}"}

    # S2: Upload Intent -> Quarantine Storage -> Complete
    intent_resp = e2e_client.post(
        "/v1/uploads",
        headers=emp_headers,
        json={
            "filename": "quarterly_report.pdf",
            "size_bytes": len(PDF_PAYLOAD),
            "content_type": "application/pdf",
        },
    )
    assert intent_resp.status_code == 201, intent_resp.text
    intent_data = intent_resp.json()
    upload_id = uuid.UUID(intent_data["upload_id"])

    # Simulate client writing bytes to quarantine
    quarantine_k = quarantine_key(tenant_1, upload_id)
    e2e_storage.put(quarantine_k, io.BytesIO(PDF_PAYLOAD), content_type="application/pdf")

    # Complete upload: promotes blob and fires worker chain (synchronously in eager mode)
    complete_resp = e2e_client.post(
        f"/v1/uploads/{upload_id}/complete",
        headers=emp_headers,
        json={"size_bytes": len(PDF_PAYLOAD)},
    )
    assert complete_resp.status_code == 200, complete_resp.text
    complete_data = complete_resp.json()
    document_id = uuid.UUID(complete_data["document_id"])
    assert document_id == upload_id

    # S3: Pipeline state verification
    doc_resp = e2e_client.get(f"/v1/documents/{document_id}", headers=emp_headers)
    assert doc_resp.status_code == 200, doc_resp.text
    doc_data = doc_resp.json()
    assert doc_data["status"] == "ready"
    assert doc_data["level"] == "Internal"
    assert doc_data["filename"] == "quarterly_report.pdf"

    # Verify 6 stages recorded in processing_jobs in spec order
    jobs_resp = e2e_client.get(f"/v1/documents/{document_id}/jobs", headers=emp_headers)
    assert jobs_resp.status_code == 200, jobs_resp.text
    jobs_data = jobs_resp.json()
    assert len(jobs_data) == 6
    expected_stages = ["scan", "extract", "keywords", "embed", "classify", "index"]
    assert [j["stage"] for j in jobs_data] == expected_stages
    assert all(j["state"] == "succeeded" for j in jobs_data)

    # Verify review queue visibility
    review_resp = e2e_client.get("/v1/review", headers=admin_headers)
    assert review_resp.status_code == 200, review_resp.text
    review_items = review_resp.json()["items"]
    assert len(review_items) == 1
    review_item = review_items[0]
    assert review_item["document_id"] == str(document_id)
    review_id = uuid.UUID(review_item["review_id"])

    # S4: Human Review Resolution (Raise to Confidential) -> then Lower (to Internal)
    resolve_resp = e2e_client.post(
        f"/v1/review/{review_id}/resolve",
        headers=admin_headers,
        json={"level_name": "confidential", "decision": "accept"},
    )
    assert resolve_resp.status_code == 200, resolve_resp.text
    assert resolve_resp.json()["level"] == "confidential"
    assert resolve_resp.json()["decided_by"] == "human"

    # Verify review item is now resolved
    review_after = e2e_client.get("/v1/review", headers=admin_headers)
    assert review_after.json()["items"] == []

    # Human lowering back to Internal (allowed for human decided_by per #8 check_monotonic)
    lower_resp = e2e_client.post(
        f"/v1/documents/{document_id}/classification",
        headers=admin_headers,
        json={"level_name": "internal"},
    )
    assert lower_resp.status_code == 200, lower_resp.text
    assert lower_resp.json()["level"] == "internal"

    # Verify append-only classifications history and access_log audit rows in DB
    with psycopg.connect(migrated_db.libpq_url, autocommit=True) as conn:
        conn.execute("SELECT set_config('app.tenant_id', %s, true)", (str(tenant_1),))
        cls_rows = conn.execute(
            "SELECT c.decided_by, s.name FROM classifications c "
            "JOIN security_levels s ON c.level_id = s.id "
            "WHERE c.document_id = %s ORDER BY c.created_at ASC",
            (document_id,),
        ).fetchall()
        assert len(cls_rows) == 3
        assert cls_rows[0] == ("rules", "Internal")
        assert cls_rows[1] == ("human", "Confidential")
        assert cls_rows[2] == ("human", "Internal")

        audit_actions = [
            row[0]
            for row in conn.execute(
                "SELECT action FROM access_log WHERE document_id = %s ORDER BY ts ASC",
                (document_id,),
            ).fetchall()
        ]
        assert "upload.init" in audit_actions
        assert "upload.complete" in audit_actions
        assert "reclassify.resolve.human" in audit_actions
        assert "reclassify.human" in audit_actions

    # S5: Content Split (Stream for Confidential vs Presign redirect for Internal)
    # When Internal: GET /content returns 303 Redirect to presigned URL
    content_internal = e2e_client.get(
        f"/v1/documents/{document_id}/content",
        headers=emp_headers,
        follow_redirects=False,
    )
    assert content_internal.status_code == 303
    assert "/v1/dev-storage/" in content_internal.headers["location"]

    # Raise back to Confidential for streaming check
    e2e_client.post(
        f"/v1/documents/{document_id}/classification",
        headers=admin_headers,
        json={"level_name": "confidential"},
    )

    # When Confidential: GET /content streams full bytes (200 OK)
    content_stream = e2e_client.get(
        f"/v1/documents/{document_id}/content",
        headers=admin_headers,
    )
    assert content_stream.status_code == 200
    assert content_stream.content == PDF_PAYLOAD
    assert content_stream.headers["Content-Length"] == str(len(PDF_PAYLOAD))

    # Range header request on Confidential content (206 Partial Content)
    content_range = e2e_client.get(
        f"/v1/documents/{document_id}/content",
        headers={**admin_headers, "Range": "bytes=0-9"},
    )
    assert content_range.status_code == 206
    assert content_range.content == PDF_PAYLOAD[:10]
    assert content_range.headers["Content-Range"] == f"bytes 0-9/{len(PDF_PAYLOAD)}"

    # S6: Cross-Tenant 404 Parity (#31)
    non_existent_id = uuid.uuid4()
    canon_404_body = not_found().body

    for path in (
        f"/v1/documents/{document_id}",
        f"/v1/documents/{document_id}/content",
        f"/v1/documents/{document_id}/findings",
        f"/v1/documents/{document_id}/jobs",
    ):
        resp = e2e_client.get(path, headers=outsider_headers)
        assert resp.status_code == 404
        assert resp.content == canon_404_body

    # Verify byte-identical response against a truly nonexistent document
    nonexistent_resp = e2e_client.get(f"/v1/documents/{non_existent_id}", headers=outsider_headers)
    assert nonexistent_resp.status_code == 404
    assert nonexistent_resp.content == canon_404_body


def test_e2e_clamav_eicar_malware_rejection(
    migrated_db: DbTarget,
    e2e_settings: Settings,
    e2e_storage: LocalStorage,
    eager_pipeline: None,
    e2e_client: TestClient,
) -> None:
    """S7: Upload of EICAR test string triggers ClamAV rejection and sets status=failed."""
    tenant = uuid.uuid4()
    dept = uuid.uuid4()

    with psycopg.connect(migrated_db.libpq_url, autocommit=True) as conn:
        conn.execute("INSERT INTO tenants (id, name) VALUES (%s, 'Malware Test Tenant')", (tenant,))
        conn.execute(
            "INSERT INTO departments (id, tenant_id, parent_id, name) VALUES (%s, %s, NULL, 'SecOps')",
            (dept, tenant),
        )

    token = issue_dev_token(
        "dev-secops", tenant, dept, "admin", 4, audience="docmgmt-api", secret=DEV_SECRET
    )
    headers = {"Authorization": f"Bearer {token}"}

    # Intent
    intent_resp = e2e_client.post(
        "/v1/uploads",
        headers=headers,
        json={
            "filename": "eicar_test.pdf",
            "size_bytes": len(EICAR_PAYLOAD),
            "content_type": "application/pdf",
        },
    )
    assert intent_resp.status_code == 201, intent_resp.text
    upload_id = uuid.UUID(intent_resp.json()["upload_id"])

    # Put EICAR payload into quarantine
    quarantine_k = quarantine_key(tenant, upload_id)
    e2e_storage.put(quarantine_k, io.BytesIO(EICAR_PAYLOAD), content_type="application/pdf")

    # Complete upload: eager worker chain runs and fails at scan stage due to ClamAV EICAR signature
    complete_resp = e2e_client.post(
        f"/v1/uploads/{upload_id}/complete",
        headers=headers,
        json={"size_bytes": len(EICAR_PAYLOAD)},
    )
    assert complete_resp.status_code == 200, complete_resp.text

    # Verify SQL-visible failure state (#4)
    doc_resp = e2e_client.get(f"/v1/documents/{upload_id}", headers=headers)
    assert doc_resp.status_code == 200, doc_resp.text
    assert doc_resp.json()["status"] == "failed"

    # Verify scan stage in processing_jobs recorded as failed with malware error
    jobs_resp = e2e_client.get(f"/v1/documents/{upload_id}/jobs", headers=headers)
    assert jobs_resp.status_code == 200, jobs_resp.text
    jobs_list = jobs_resp.json()
    assert len(jobs_list) >= 1
    scan_job = next(j for j in jobs_list if j["stage"] == "scan")
    assert scan_job["state"] == "failed"
    assert "malware detected" in (scan_job["error"] or "").lower()
