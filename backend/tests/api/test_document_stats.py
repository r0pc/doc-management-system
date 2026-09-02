"""Tests for document analytics and statistics endpoint (spec section 3.2, #25, #27, #28)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest

from app.api.v1 import documents as documents_module
from app.api.v1.documents import (
    DailyIngestionStat,
    DecisionSourceStat,
    DepartmentStat,
    DocTypeStat,
    DocumentStatsOut,
    LevelStat,
    RecentDocumentStat,
    StatusBreakdown,
)

PATH = "/v1/documents/stats"


class TestDocumentStatsEndpoint:
    def test_stats_happy_path(self, client_factory: Any, monkeypatch: pytest.MonkeyPatch) -> None:
        client = client_factory(role="employee")

        doc_id = uuid.uuid4()
        dept_id = uuid.uuid4()
        sample_stats = DocumentStatsOut(
            total_documents=10,
            total_storage_bytes=1048576,
            status_breakdown=StatusBreakdown(
                ready=8,
                processing=1,
                quarantined=0,
                failed=1,
                held=0,
            ),
            levels_breakdown=[
                LevelStat(name="Public", rank=1, count=2, percentage=20.0),
                LevelStat(name="Internal", rank=2, count=5, percentage=50.0),
                LevelStat(name="Confidential", rank=3, count=2, percentage=20.0),
                LevelStat(name="Restricted", rank=4, count=1, percentage=10.0),
            ],
            doc_types_breakdown=[
                DocTypeStat(name="Contract", count=6, percentage=60.0),
                DocTypeStat(name="Invoice", count=4, percentage=40.0),
            ],
            departments_breakdown=[
                DepartmentStat(id=dept_id, name="Engineering", count=6),
            ],
            decision_sources=[
                DecisionSourceStat(source="ml", count=7),
                DecisionSourceStat(source="rule", count=3),
            ],
            daily_ingestion=[
                DailyIngestionStat(date="2026-09-01", count=4),
                DailyIngestionStat(date="2026-09-02", count=6),
            ],
            recent_documents=[
                RecentDocumentStat(
                    id=doc_id,
                    filename="sample_contract.pdf",
                    status="ready",
                    level="Internal",
                    doc_type="Contract",
                    created_at=datetime(2026, 9, 2, 10, 0, tzinfo=UTC),
                ),
            ],
            avg_confidence=0.92,
            pending_reviews_count=1,
        )

        async def fake_fetch_stats(session: Any, user: Any) -> DocumentStatsOut:
            return sample_stats

        monkeypatch.setattr(documents_module, "_fetch_document_stats", fake_fetch_stats)

        response = client.get(PATH)
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["total_documents"] == 10
        assert data["total_storage_bytes"] == 1048576
        assert data["status_breakdown"]["ready"] == 8
        assert data["status_breakdown"]["failed"] == 1
        assert len(data["levels_breakdown"]) == 4
        assert data["levels_breakdown"][1]["name"] == "Internal"
        assert data["levels_breakdown"][1]["count"] == 5
        assert len(data["doc_types_breakdown"]) == 2
        assert data["doc_types_breakdown"][0]["name"] == "Contract"
        assert len(data["departments_breakdown"]) == 1
        assert data["departments_breakdown"][0]["name"] == "Engineering"
        assert data["avg_confidence"] == 0.92
        assert data["pending_reviews_count"] == 1
        assert len(data["recent_documents"]) == 1
        assert data["recent_documents"][0]["filename"] == "sample_contract.pdf"
