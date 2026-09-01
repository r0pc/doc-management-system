"""SQLAlchemy ORM models mirroring spec §6 exactly (16 tables) plus §6.2 indexes.

# allow: SIZE_OK - declarative 1:1 transcription of spec §6/§6.2 (pure data
# tables); splitting would fragment the schema contract across files that
# Alembic autogenerate and Wave 2.A treat as one unit.

Invariants encoded structurally here, not by convention:
- #12  findings store character offsets only - never matched text.
- #15  blobs carry no tenant and no permission columns.
- #21  classifications reference version_id, not just document_id.
- #22  documents.current_classification_id is DEFERRABLE INITIALLY DEFERRED
       (mutually circular with classifications.document_id); use_alter so DDL
       emits after both tables exist.
- #23  security_levels.rank is a separate UNIQUE column; the PK stays the
       surrogate id.
- #24  access_log.document_id / actor_id are bare uuids with no ForeignKey -
       the audit trail survives deletes of what it audits.

No ORM relationships are declared: this is the persistence layer only, and the
circular FK pair would force relationship() ceremony nothing consumes yet.
"""

from __future__ import annotations

import datetime
import uuid
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    REAL,
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, INET, JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import UserDefinedType

from app.db.base import Base


class TSVector(UserDefinedType[str]):
    """Minimal PostgreSQL ``tsvector`` type. Hand-rolled: no new dependency."""

    cache_ok = True

    def get_col_spec(self, **kw: object) -> str:
        return "tsvector"


class Tenant(Base):
    __tablename__ = "tenants"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Department(Base):
    __tablename__ = "departments"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"))
    parent_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("departments.id"))
    name: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class DocumentDepartment(Base):
    """Which departments a document belongs to (#25, axis 2).

    Composite PK, so a document cannot be joined to the same department twice.
    ``tenant_id`` is denormalised from the document purely so the RLS policy can
    scope on this table directly instead of joining back to ``documents``.
    """

    __tablename__ = "document_departments"

    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), primary_key=True
    )
    department_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("departments.id"), primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"))


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"))
    department_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("departments.id"))
    oidc_sub: Mapped[str] = mapped_column(Text, unique=True)
    email: Mapped[str] = mapped_column(Text)
    role: Mapped[str] = mapped_column(Text)
    clearance_rank: Mapped[int] = mapped_column(SmallInteger)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Blob(Base):
    """Content-addressed bytes. No tenant, no permission (#15)."""

    __tablename__ = "blobs"

    sha256: Mapped[str] = mapped_column(Text, primary_key=True)
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    mime_sniffed: Mapped[str] = mapped_column(Text)
    bucket_key: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Document(Base):
    __tablename__ = "documents"
    __table_args__ = (
        CheckConstraint(
            "status IN ('quarantined', 'processing', 'ready', 'failed', 'held')",
            name="status_valid",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"))
    department_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("departments.id"))
    original_filename: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text)
    current_classification_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey(
            "classifications.id",
            deferrable=True,
            initially="DEFERRED",
            use_alter=True,
        )
    )
    uploaded_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    deleted_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))


class DocumentVersion(Base):
    __tablename__ = "document_versions"
    __table_args__ = (UniqueConstraint("document_id", "version_no"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id"))
    blob_sha256: Mapped[str | None] = mapped_column(Text, ForeignKey("blobs.sha256"), nullable=True)
    version_no: Mapped[int] = mapped_column(Integer)
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class SecurityLevel(Base):
    """Surrogate id PK; rank is a separate UNIQUE column, never the key (#23)."""

    __tablename__ = "security_levels"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    rank: Mapped[int] = mapped_column(SmallInteger, unique=True)
    name: Mapped[str] = mapped_column(Text, unique=True)
    description: Mapped[str] = mapped_column(Text)


class DocType(Base):
    __tablename__ = "doc_types"
    __table_args__ = (UniqueConstraint("parent_id", "name"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("doc_types.id"))
    name: Mapped[str] = mapped_column(Text)
    description: Mapped[str] = mapped_column(Text)
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("tenants.id"), nullable=True)


class ProcessingJob(Base):
    __tablename__ = "processing_jobs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id"))
    version_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("document_versions.id"))
    stage: Mapped[str] = mapped_column(Text)  # scan|extract|keywords|embed|classify|index
    state: Mapped[str] = mapped_column(Text)  # queued|running|succeeded|failed|skipped
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))


class Keyword(Base):
    __tablename__ = "keywords"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    term: Mapped[str] = mapped_column(Text, unique=True)
    idf: Mapped[float] = mapped_column(REAL)


class DocumentKeyword(Base):
    __tablename__ = "document_keywords"

    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id"), primary_key=True)
    keyword_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("keywords.id"), primary_key=True)
    score: Mapped[float] = mapped_column(REAL)


class DocumentText(Base):
    __tablename__ = "document_text"

    version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("document_versions.id"), primary_key=True
    )
    tsv: Mapped[TSVector] = mapped_column(TSVector)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(384))
    char_count: Mapped[int] = mapped_column(Integer)
    ocr_used: Mapped[bool] = mapped_column(Boolean)


class Classification(Base):
    """Append-only history row; references a version, not just a document (#21)."""

    __tablename__ = "classifications"
    __table_args__ = (
        CheckConstraint("decided_by IN ('rules', 'ml', 'human')", name="decided_by_valid"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id"))
    version_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("document_versions.id"))
    level_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("security_levels.id"))
    doc_type_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("doc_types.id"))
    confidence: Mapped[float | None] = mapped_column(REAL)
    decided_by: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Finding(Base):
    """One rule firing at one character offset. Offsets only, never text (#12)."""

    __tablename__ = "findings"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    classification_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("classifications.id"))
    entity_type: Mapped[str] = mapped_column(Text)
    rule_id: Mapped[str] = mapped_column(Text)
    page_no: Mapped[int | None] = mapped_column(Integer)
    char_start: Mapped[int] = mapped_column(Integer)
    char_end: Mapped[int] = mapped_column(Integer)
    score: Mapped[float] = mapped_column(REAL)


class ReviewItem(Base):
    __tablename__ = "review_items"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id"))
    assigned_to: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    state: Mapped[str] = mapped_column(Text)  # pending|claimed|resolved
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    resolved_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))


class AccessLog(Base):
    """Audit trail that outlives what it audits (#24): bare uuids, no FKs."""

    __tablename__ = "access_log"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    document_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    action: Mapped[str] = mapped_column(Text)
    ip: Mapped[str | None] = mapped_column(INET)
    user_agent: Mapped[str | None] = mapped_column(Text)
    detail: Mapped[str | None] = mapped_column(Text)
    ts: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True))


class DocTypePrototype(Base):
    __tablename__ = "doc_type_prototypes"
    __table_args__ = (
        UniqueConstraint("tenant_id", "doc_type_id", name="uq_doc_type_prototypes_tenant_doctype"),
        CheckConstraint("sample_count >= 5", name="chk_doc_type_prototypes_sample_count"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"))
    doc_type_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("doc_types.id"))
    centroid_vector: Mapped[list[float]] = mapped_column(Vector(384))
    sample_count: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class DetectorRule(Base):
    __tablename__ = "detector_rules"
    __table_args__ = (
        UniqueConstraint("tenant_id", "entity_type", name="uq_detector_rules_tenant_entity"),
        CheckConstraint("cardinality(context_words) > 0", name="chk_detector_rules_context_words"),
        CheckConstraint("level_rank BETWEEN 1 AND 4", name="chk_detector_rules_level_rank"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"))
    entity_type: Mapped[str] = mapped_column(Text)
    pattern: Mapped[str] = mapped_column(Text)
    validator_kind: Mapped[str] = mapped_column(Text)
    validator_config: Mapped[dict[str, Any]] = mapped_column(
        JSONB, server_default=text("'{}'::jsonb")
    )
    context_words: Mapped[list[str]] = mapped_column(ARRAY(Text))
    level_rank: Mapped[int] = mapped_column(Integer)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


# --- spec §6.2 indexes, in spec order; names pinned for deterministic autogenerate ---
Index(
    "ix_documents_tenant_status",
    Document.__table__.c.tenant_id,
    Document.__table__.c.status,
    postgresql_where=text("deleted_at IS NULL"),
)
Index(
    "ix_document_versions_doc_version",
    DocumentVersion.__table__.c.document_id,
    DocumentVersion.__table__.c.version_no.desc(),
)
Index(
    "ix_classifications_doc_created",
    Classification.__table__.c.document_id,
    Classification.__table__.c.created_at.desc(),
)
Index(
    "ix_access_log_document_ts",
    AccessLog.__table__.c.document_id,
    AccessLog.__table__.c.ts.desc(),
)
Index("ix_access_log_actor_ts", AccessLog.__table__.c.actor_id, AccessLog.__table__.c.ts.desc())
# §6.2's CREATE UNIQUE INDEX on (document_id, version_no) is carried by the
# UniqueConstraint above - one enforcement, not two.
Index(
    "ix_documents_tenant_department",
    Document.__table__.c.tenant_id,
    Document.__table__.c.department_id,
    postgresql_where=text("deleted_at IS NULL"),
)
Index(
    "ix_processing_jobs_document_stage",
    ProcessingJob.__table__.c.document_id,
    ProcessingJob.__table__.c.stage,
)
Index(
    "ix_processing_jobs_state_live",
    ProcessingJob.__table__.c.state,
    postgresql_where=text("state IN ('queued', 'running')"),
)
Index("ix_document_text_tsv_gin", DocumentText.__table__.c.tsv, postgresql_using="gin")
Index(
    "ix_document_text_embedding_hnsw",
    DocumentText.__table__.c.embedding,
    postgresql_using="hnsw",
    postgresql_ops={"embedding": "vector_cosine_ops"},
)
Index(
    "ix_document_keywords_keyword_score",
    DocumentKeyword.__table__.c.keyword_id,
    DocumentKeyword.__table__.c.score.desc(),
)
Index(
    "idx_doc_type_prototypes_hnsw",
    DocTypePrototype.__table__.c.centroid_vector,
    postgresql_using="hnsw",
    postgresql_ops={"centroid_vector": "vector_cosine_ops"},
)
