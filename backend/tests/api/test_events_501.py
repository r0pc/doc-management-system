"""GET /v1/events 501 stub contract test.

Pins the exact problem+json body, media type and status so the frontend wave
can code against the contract before SSE ships. The route keeps the standard
auth dependency so unauthenticated probes behave like any real endpoint.
"""

from typing import Any

EXPECTED_BODY = {
    "type": "https://dms.example/problems/not-implemented",
    "title": "Not Implemented",
    "status": 501,
    "detail": "SSE arrives with frontend wave; poll GET /v1/documents/{id}/jobs meanwhile",
}


def test_events_stub_contract(client: Any) -> None:
    response = client.get("/v1/events")
    assert response.status_code == 501
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json() == EXPECTED_BODY


def test_events_requires_auth(raw_client: Any) -> None:
    assert raw_client.get("/v1/events").status_code == 401
