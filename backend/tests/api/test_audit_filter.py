"""Audit read endpoint tests (#24 posture).

Real code under test: role gating (VIEW_AUDIT), exact-match filter
forwarding, keyset windowing on (ts DESC, id DESC) with the bigserial
tiebreaker, limit clamping (never rejection) and the read-only route surface:
no mutation method may exist under /v1/audit.
"""

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest

from app.api.v1.audit import AuditLogEntry
from tests.api.conftest import make_user

EPOCH = datetime(2026, 1, 1, tzinfo=UTC)

DOC_ID = UUID(int=0xD0C)
ACTOR_ID = UUID(int=0xF00D)

OFFICER: dict[str, object] = {"role": "security_officer", "clearance_rank": 4}


def entry(index: int, ts: datetime | None = None) -> AuditLogEntry:
    return AuditLogEntry(
        id=1000 - index,
        document_id=DOC_ID,
        actor_id=ACTOR_ID,
        action="download.presign",
        ip="127.0.0.1",
        user_agent="pytest",
        ts=ts or (EPOCH + timedelta(minutes=index)),
    )


def install_audit_fake(
    monkeypatch: pytest.MonkeyPatch, rows: list[AuditLogEntry]
) -> dict[str, Any]:
    captured: dict[str, Any] = {}

    async def page(
        session: Any,
        filters: Any,
        after: tuple[datetime, int] | None,
        limit_plus_one: int,
    ) -> list[AuditLogEntry]:
        captured["filters"] = filters
        captured["after"] = after
        captured["limit_plus_one"] = limit_plus_one
        ordered = sorted(rows, key=lambda r: (r.ts, r.id), reverse=True)
        if after is not None:
            ordered = [r for r in ordered if (r.ts, r.id) < after]
        return ordered[:limit_plus_one]

    monkeypatch.setattr("app.api.v1.audit._fetch_audit_page", page)
    return captured


def officer_client(client_factory: Any) -> Any:
    return client_factory(user=make_user(**OFFICER))  # type: ignore[arg-type]


def test_filters_forwarded_verbatim(client_factory: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    captured = install_audit_fake(monkeypatch, [])
    response = officer_client(client_factory).get(
        "/v1/audit",
        params={
            "document_id": str(DOC_ID),
            "actor_id": str(ACTOR_ID),
            "action": "download.presign",
        },
    )
    assert response.status_code == 200
    assert captured["filters"].document_id == DOC_ID
    assert captured["filters"].actor_id == ACTOR_ID
    assert captured["filters"].action == "download.presign"


def test_no_filters_means_all_none(client_factory: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    captured = install_audit_fake(monkeypatch, [])
    assert officer_client(client_factory).get("/v1/audit").status_code == 200
    assert captured["filters"].document_id is None
    assert captured["filters"].actor_id is None
    assert captured["filters"].action is None


def test_limit_clamped_not_rejected(client_factory: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    captured = install_audit_fake(monkeypatch, [])
    response = officer_client(client_factory).get("/v1/audit", params={"limit": 9999})
    assert response.status_code == 200
    assert captured["limit_plus_one"] == 201


def test_keyset_cursor_descends_ts_then_id(
    client_factory: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    rows = [entry(i) for i in range(4)]
    captured = install_audit_fake(monkeypatch, rows)
    client = officer_client(client_factory)
    first = client.get("/v1/audit", params={"limit": 2}).json()
    # Newest first: entry(3) then entry(2); the cursor anchors on the LAST item.
    anchor = sorted(rows, key=lambda r: (r.ts, r.id), reverse=True)[1]
    second = client.get("/v1/audit", params={"limit": 2, "cursor": first["next_cursor"]}).json()
    assert [item["id"] for item in second["items"]] == [rows[1].id, rows[0].id]
    assert captured["after"] == (anchor.ts, anchor.id)


def test_employee_and_viewer_are_403(client_factory: Any) -> None:
    for role in ("employee", "viewer"):
        client = client_factory(user=make_user(role=role))
        assert client.get("/v1/audit").status_code == 403


def test_audit_requires_token(raw_client: Any) -> None:
    assert raw_client.get("/v1/audit").status_code == 401


def test_no_mutation_routes_exist_under_audit(client: Any) -> None:
    """#24 posture is structural: the router defines no write methods at all."""
    methods: set[str] = set()
    for path, ops in client.app.openapi()["paths"].items():
        if path.startswith("/v1/audit"):
            methods |= {method.upper() for method in ops}
    assert methods == {"GET"}
