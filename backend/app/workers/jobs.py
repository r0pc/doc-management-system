"""Worker-side durable state: the processing_jobs journal and pipeline SQL.

# allow: SIZE_OK - the wave spec freezes this file list (tasks/jobs/scanning
# only); journal + persistence SQL cannot split into a further module without
# violating that constraint. Revisit at the next wave boundary.

Every journal write is its own short transaction (#4): a worker crash between
stages leaves a truthful ``processing_jobs`` trail answerable from SQL alone.
The journal rows are get-or-created keyed on ``(version_id, stage)`` so retries
update one row instead of spawning duplicates.

The persistence helpers below are the ONLY SQL the pipeline stages issue for
domain tables (blobs/keywords/classifications/document_text/documents); the
stage tasks stay orchestration-only. They run against a sync engine built from
``Settings.sync_db_url`` — Celery workers are synchronous by design.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Final, Protocol, TypeVar

from sqlalchemy import delete, select, text, update
from sqlalchemy.engine import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.classification.ml.artifact import taxonomy_name_for_label
from app.classification.pipeline import ClassificationOutcome
from app.config import Settings
from app.db.models import (
    Blob,
    Classification,
    DocType,
    DocTypePrototype,
    Document,
    DocumentKeyword,
    DocumentVersion,
    Finding,
    Keyword,
    ProcessingJob,
    ReviewItem,
    SecurityLevel,
)

logger = logging.getLogger(__name__)

T = TypeVar("T")

PENDING_REVIEW_STATE: Final = "pending"
HUMAN_DECIDED_BY: Final = "human"


_sync_sessions: sessionmaker[Session] | None = None


def get_sync_sessions(settings: Settings | None = None) -> sessionmaker[Session]:
    """Process-wide sync session factory, created lazily (import never dials out)."""
    global _sync_sessions
    if _sync_sessions is None:
        resolved = settings if settings is not None else Settings()
        engine = create_engine(resolved.sync_db_url, echo=False)
        _sync_sessions = sessionmaker(bind=engine, expire_on_commit=False)
    return _sync_sessions


class JobsJournal(Protocol):
    """State-journal surface every stage task relies on (#4)."""

    def has_succeeded(self, version_id: str | uuid.UUID, stage: str) -> bool: ...

    def mark_queued(self, version_id: str | uuid.UUID, stage: str) -> uuid.UUID: ...

    def mark_running(
        self, document_id: str | uuid.UUID, version_id: str | uuid.UUID, stage: str
    ) -> uuid.UUID: ...

    def mark_succeeded(self, job_row_id: uuid.UUID) -> None: ...

    def mark_failed(self, job_row_id: uuid.UUID, error: str) -> None: ...

    def mark_skipped(self, job_row_id: uuid.UUID, reason: str) -> None: ...


class ProcessingJobsJournal:
    """SQL-backed journal over ``processing_jobs``; one transaction per write."""

    def __init__(self, sessions: sessionmaker[Session]) -> None:
        self._sessions = sessions

    def _write(self, operation: Callable[[Session], T]) -> T:
        with self._sessions() as session, session.begin():
            return operation(session)

    @staticmethod
    def _find_job(session: Session, version_id: uuid.UUID, stage: str) -> uuid.UUID | None:
        return session.execute(
            select(ProcessingJob.id).where(
                ProcessingJob.version_id == version_id, ProcessingJob.stage == stage
            )
        ).scalar_one_or_none()

    def has_succeeded(self, version_id: str | uuid.UUID, stage: str) -> bool:
        """#5 guard: answers purely from stored state, never from counters."""
        vid = uuid.UUID(str(version_id))
        return self._write(
            lambda session: (
                session.execute(
                    select(ProcessingJob.id).where(
                        ProcessingJob.version_id == vid,
                        ProcessingJob.stage == stage,
                        ProcessingJob.state == "succeeded",
                    )
                ).first()
                is not None
            )
        )

    def mark_queued(self, version_id: str | uuid.UUID, stage: str) -> uuid.UUID:
        vid = uuid.UUID(str(version_id))

        def op(session: Session) -> uuid.UUID:
            existing = self._find_job(session, vid, stage)
            if existing is not None:
                return existing
            document_id = session.execute(
                select(DocumentVersion.document_id).where(DocumentVersion.id == vid)
            ).scalar_one()
            row = ProcessingJob(
                document_id=document_id, version_id=vid, stage=stage, state="queued", attempts=0
            )
            session.add(row)
            session.flush()
            return row.id

        return self._write(op)

    def mark_running(
        self, document_id: str | uuid.UUID, version_id: str | uuid.UUID, stage: str
    ) -> uuid.UUID:
        vid = uuid.UUID(str(version_id))

        def op(session: Session) -> uuid.UUID:
            job_id = self._find_job(session, vid, stage)
            if job_id is None:
                row = ProcessingJob(
                    document_id=uuid.UUID(str(document_id)),
                    version_id=vid,
                    stage=stage,
                    state="running",
                    attempts=1,
                    started_at=datetime.now(UTC),
                )
                session.add(row)
                session.flush()
                return row.id
            session.execute(
                update(ProcessingJob)
                .where(ProcessingJob.id == job_id)
                .values(
                    state="running",
                    attempts=ProcessingJob.attempts + 1,
                    started_at=datetime.now(UTC),
                    finished_at=None,
                )
            )
            return job_id

        return self._write(op)

    def mark_succeeded(self, job_row_id: uuid.UUID) -> None:
        def op(session: Session) -> None:
            session.execute(
                update(ProcessingJob)
                .where(ProcessingJob.id == job_row_id)
                .values(state="succeeded", error=None, finished_at=datetime.now(UTC))
            )

        self._write(op)

    def mark_failed(self, job_row_id: uuid.UUID, error: str) -> None:
        def op(session: Session) -> None:
            session.execute(
                update(ProcessingJob)
                .where(ProcessingJob.id == job_row_id)
                .values(state="failed", error=error, finished_at=datetime.now(UTC))
            )

        self._write(op)

    def mark_skipped(self, job_row_id: uuid.UUID, reason: str) -> None:
        def op(session: Session) -> None:
            session.execute(
                update(ProcessingJob)
                .where(ProcessingJob.id == job_row_id)
                .values(state="skipped", error=reason, finished_at=datetime.now(UTC))
            )

        self._write(op)


def load_version_context(
    sessions: sessionmaker[Session], document_id: uuid.UUID, version_id: uuid.UUID
) -> tuple[uuid.UUID, str | None]:
    """Tenant id + recorded sha256 for the entry task's ctx dict.

    The digest is NULL for a freshly completed upload — the API signs the
    intent without ever reading the bytes (#1) — and is filled in by the
    pipeline once it hashes the quarantined object. Callers must treat the
    second element as optional.
    """
    with sessions() as session, session.begin():
        row = session.execute(
            select(Document.tenant_id, DocumentVersion.blob_sha256)
            .join(Document, Document.id == DocumentVersion.document_id)
            .where(
                DocumentVersion.id == version_id,
                DocumentVersion.document_id == document_id,
            )
        ).one()
        return row.tenant_id, row.blob_sha256


def promote_blob_record(
    sessions: sessionmaker[Session],
    *,
    sha256: str,
    size_bytes: int,
    mime_sniffed: str,
    bucket_key: str,
    version_id: uuid.UUID,
) -> None:
    """Get-or-create the content-addressed blob row, then repoint the version."""
    with sessions() as session, session.begin():
        exists = session.execute(
            select(Blob.sha256).where(Blob.sha256 == sha256)
        ).scalar_one_or_none()
        if exists is None:
            session.add(
                Blob(
                    sha256=sha256,
                    size_bytes=size_bytes,
                    mime_sniffed=mime_sniffed,
                    bucket_key=bucket_key,
                )
            )
        session.execute(
            update(DocumentVersion)
            .where(DocumentVersion.id == version_id)
            .values(blob_sha256=sha256)
        )


def replace_keywords(
    sessions: sessionmaker[Session], *, document_id: uuid.UUID, terms: list[tuple[str, float]]
) -> int:
    """Upsert keywords (idf placeholder 0.0 until corpus stats) and replace the
    document's scored links in ONE transaction (#6: computed once, atomically)."""
    with sessions() as session, session.begin():
        keyword_ids: dict[str, uuid.UUID] = {}
        for term, _score in terms:
            keyword_id = session.execute(
                select(Keyword.id).where(Keyword.term == term)
            ).scalar_one_or_none()
            if keyword_id is None:
                row = Keyword(term=term, idf=0.0)
                session.add(row)
                session.flush()
                keyword_id = row.id
            keyword_ids[term] = keyword_id
        session.execute(delete(DocumentKeyword).where(DocumentKeyword.document_id == document_id))
        for term, score in terms:
            session.add(
                DocumentKeyword(document_id=document_id, keyword_id=keyword_ids[term], score=score)
            )
    return len(terms)


def resolve_doc_type_id(session: Session, label: str | uuid.UUID | None) -> uuid.UUID | None:
    """Map a model label or UUID onto an EXISTING ``doc_types`` row; None when it can't.

    Two failure modes, both non-fatal and both logged, because a document with
    an unresolved type is strictly better than a taxonomy corrupted by model
    output:

    * the label is not one this backend knows how to name (a stale or foreign
      artifact) — ``doc_type_label_unknown``;
    * the name is known but no row carries it (the taxonomy is admin-editable
      via ``/v1/admin`` and migration 0003 does not seed every model label,
      notably "HR Letter") — ``doc_type_row_absent``, whose fix is an admin
      creating that row, not this worker inserting one.

    Rows are NOT auto-created here: ``doc_types`` is the tenant-facing
    vocabulary, and letting ingestion mint entries would let a swapped model
    silently rewrite it.
    """
    if label is None:
        return None
    if isinstance(label, uuid.UUID):
        return label
    name = taxonomy_name_for_label(label)
    if name is None:
        logger.warning("doc_type_label_unknown label=%s", label)
        return None
    # doc_types is UNIQUE(parent_id, name), so a name could in principle repeat
    # under two parents; order for determinism rather than raising on ambiguity.
    doc_type_id = session.execute(
        select(DocType.id).where(DocType.name == name).order_by(DocType.id).limit(1)
    ).scalar_one_or_none()
    if doc_type_id is None:
        logger.warning("doc_type_row_absent label=%s name=%s", label, name)
    return doc_type_id


def record_classification(
    sessions: sessionmaker[Session],
    *,
    document_id: uuid.UUID,
    version_id: uuid.UUID,
    outcome: ClassificationOutcome,
) -> uuid.UUID:
    """Append-only classification write with SELECT-before-INSERT dedup (#5).

    Monotonicity authority is the DB ``check_monotonic`` trigger (#8): an
    IntegrityError raised here propagates so the stage journals failed.

    ``outcome.doc_type`` is the ML label; :func:`resolve_doc_type_id` turns it
    into a ``doc_types`` FK (or NULL + a log line). Without this the type half
    of the cascade would be computed and thrown away, and every search facet
    would read "unknown".
    """
    with sessions() as session, session.begin():
        level_id = session.execute(
            select(SecurityLevel.id).where(SecurityLevel.rank == outcome.level_rank)
        ).scalar_one()
        existing = session.execute(
            select(Classification.id)
            .where(
                Classification.document_id == document_id,
                Classification.version_id == version_id,
                Classification.decided_by != HUMAN_DECIDED_BY,
            )
            .order_by(Classification.created_at.desc())
            .limit(1)
        ).scalar_one_or_none()
        if existing is None:
            row = Classification(
                document_id=document_id,
                version_id=version_id,
                level_id=level_id,
                doc_type_id=resolve_doc_type_id(session, outcome.doc_type),
                confidence=outcome.confidence,
                decided_by=outcome.decided_by,
            )
            session.add(row)
            session.flush()
            classification_id = row.id
            for finding in outcome.findings:
                session.add(
                    Finding(
                        classification_id=classification_id,
                        entity_type=finding.entity_type,
                        rule_id=finding.rule_id,
                        page_no=finding.page_no,
                        char_start=finding.char_start,
                        char_end=finding.char_end,
                        score=finding.score,
                    )
                )
        else:
            classification_id = existing
        if outcome.needs_review:
            pending = session.execute(
                select(ReviewItem.id)
                .where(
                    ReviewItem.document_id == document_id,
                    ReviewItem.state == PENDING_REVIEW_STATE,
                )
                .limit(1)
            ).scalar_one_or_none()
            if pending is None:
                session.add(ReviewItem(document_id=document_id, state=PENDING_REVIEW_STATE))
        # Deferred FK pair (#22) lets this write land before/after either row.
        session.execute(
            update(Document)
            .where(Document.id == document_id)
            .values(current_classification_id=classification_id)
        )
        return classification_id


def upsert_document_text(
    sessions: sessionmaker[Session],
    *,
    version_id: uuid.UUID,
    body: str,
    char_count: int,
    ocr_used: bool,
    embedding: list[float] | None = None,
) -> None:
    """Index-row upsert with optional embedding vector."""
    statement = text(
        "INSERT INTO document_text (version_id, tsv, embedding, char_count, ocr_used)"
        " VALUES (:version_id, to_tsvector('english', :body), :embedding, :char_count, :ocr_used)"
        " ON CONFLICT (version_id) DO UPDATE SET tsv = EXCLUDED.tsv,"
        " embedding = COALESCE(EXCLUDED.embedding, document_text.embedding),"
        " char_count = EXCLUDED.char_count, ocr_used = EXCLUDED.ocr_used"
    )
    with sessions() as session, session.begin():
        session.execute(
            statement,
            {
                "version_id": str(version_id),
                "body": body,
                "embedding": str(embedding) if embedding is not None else None,
                "char_count": char_count,
                "ocr_used": ocr_used,
            },
        )


def mark_document_ready(sessions: sessionmaker[Session], document_id: uuid.UUID) -> None:
    with sessions() as session, session.begin():
        session.execute(update(Document).where(Document.id == document_id).values(status="ready"))


def mark_document_failed(sessions: sessionmaker[Session], *, document_id: uuid.UUID) -> None:
    """Terminal-failure flip so a halted chain never leaves 'processing' rows.

    Pipeline state must be answerable from SQL (#4): a malware halt journals
    the scan stage AND flips documents.status to 'failed' (an allowed value of
    the status_valid check) so operators see the outcome without joining
    processing_jobs.
    """
    with sessions() as session, session.begin():
        session.execute(update(Document).where(Document.id == document_id).values(status="failed"))


def mark_document_held(sessions: sessionmaker[Session], *, document_id: uuid.UUID) -> None:
    """Terminal 'held' flip for a document blocked on a capability we lack.

    'held' is distinct from 'failed': the document is intact and will process
    once the missing capability (today: OCR) exists. Without this flip the row
    sits at 'processing' forever with no worker that will ever pick it up (#4).
    """
    with sessions() as session, session.begin():
        session.execute(update(Document).where(Document.id == document_id).values(status="held"))


def load_tenant_prototypes(
    sessions: sessionmaker[Session], tenant_id: uuid.UUID
) -> list[tuple[uuid.UUID, list[float]]]:
    """Load all trained prototypes for the tenant."""
    with sessions() as session:
        rows = session.execute(
            select(DocTypePrototype.doc_type_id, DocTypePrototype.centroid_vector).where(
                DocTypePrototype.tenant_id == tenant_id
            )
        ).all()
        return [(row[0], list(row[1])) for row in rows if row[1] is not None]
