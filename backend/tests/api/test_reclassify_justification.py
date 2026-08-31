"""#8: a human lowering a label is audited — including why.

The modal requires a justification and sends it; the request model dropped it.
"""

from __future__ import annotations

import uuid
from typing import Any

from tests.api.conftest import make_user
from tests.api.test_reclassify_audit import install_happy_fakes


def test_justification_reaches_the_audit_row(client_factory, journal, monkeypatch) -> None:
    captured: dict[str, Any] = {}
    install_happy_fakes(monkeypatch, captured)
    client = client_factory(user=make_user(role="admin"))

    response = client.post(
        f"/v1/documents/{uuid.uuid4()}/classification",
        json={
            "level_name": "internal",
            "doc_type_id": None,
            "justification": "Reviewed with legal; contains no client identifiers.",
        },
    )
    assert response.status_code == 200
    entry = journal[-1]
    assert entry["action"] == "reclassify.human"
    assert "Reviewed with legal" in (entry.get("detail") or "")


def test_justification_is_optional_when_not_lowering(client_factory, monkeypatch) -> None:
    captured: dict[str, Any] = {}
    install_happy_fakes(monkeypatch, captured)
    client = client_factory(user=make_user(role="admin"))

    response = client.post(
        f"/v1/documents/{uuid.uuid4()}/classification",
        json={"level_name": "restricted", "doc_type_id": None},
    )
    assert response.status_code == 200


def test_overlong_justification_is_rejected(client_factory, monkeypatch) -> None:
    captured: dict[str, Any] = {}
    install_happy_fakes(monkeypatch, captured)
    client = client_factory(user=make_user(role="admin"))

    response = client.post(
        f"/v1/documents/{uuid.uuid4()}/classification",
        json={"level_name": "internal", "doc_type_id": None, "justification": "x" * 5000},
    )
    assert response.status_code == 400
