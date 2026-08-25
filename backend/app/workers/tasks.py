"""Pipeline stage tasks: fixed chain scan -> extract -> keywords -> embed ->
classify -> index (spec §7.3, invariant #3). Workers are the only automated
writer of classifications (#2); the API never classifies in-request.

# allow: SIZE_OK - the wave spec freezes this file list (tasks/jobs/scanning
# only); six stages + failure map + typed celery adapter cannot split into
# further modules without violating that constraint. Revisit at the next wave
# boundary (candidates: storage/settings accessors, derived-artifact IO).

Broker payloads stay tiny: stages pass a six-key ctx dict of string ids only;
extracted text travels via the derived object ``docs-derived/{sha}/text.json``
and downstream stages re-read it from storage (#6: extracted once, reused).
Every stage wraps its body in :func:`_run_stage`, which owns the idempotency
guard (#5), the processing_jobs lifecycle (#4) and the failure taxonomy.

Chain-halt choice: the OCR handoff dispatches ``enqueue_ocr`` onto the dedicated
queue, journals the extract stage skipped, then raises
:class:`celery.exceptions.Ignore` — Celery fires chain continuations on success
only, so Ignore halts the remaining links cleanly without surfacing as an error.
"""

import hashlib
import io
import json
import logging
import os
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Protocol, TypedDict, TypeVar

from celery import chain, shared_task
from celery.exceptions import Ignore
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.classification.pipeline import classify as run_classification
from app.config import Settings
from app.domain.taxonomy import Taxonomy
from app.extraction.base import NeedsOcrError, ParserUnavailable, UnknownMimeError
from app.extraction.keywords import FrequencyFallback
from app.extraction.registry import extract_document
from app.storage.base import BlobExistsError, Storage
from app.storage.keys import bucket_name, derived_key, primary_key
from app.storage.local import LocalStorage
from app.workers.jobs import (
    ProcessingJobsJournal,
    get_sync_sessions,
    load_version_context,
    mark_document_ready,
    promote_blob_record,
    record_classification,
    replace_keywords,
    upsert_document_text,
)
from app.workers.scanning import CLAMAV_HOST, CLAMAV_PORT, ScanError, clamd_scan

logger = logging.getLogger(__name__)


class RegisteredTask(Protocol):
    """The surface worker code uses on a registered celery task."""

    def __call__(self, *args: object, **kwargs: object) -> object: ...

    def s(self, *args: object) -> object: ...

    def apply_async(
        self,
        *,
        args: list[object] | None = None,
        kwargs: dict[str, object] | None = None,
        **options: object,
    ) -> object: ...


def pipeline_task(**options: object) -> Callable[[Callable[..., object]], RegisteredTask]:
    """Typed passthrough to ``celery.shared_task``.

    celery ships no type stubs (pyproject ignores the missing imports); this
    adapter keeps every task body strictly checked while isolating the untyped
    boundary to one line — the same narrow-exception policy as app/storage/s3.py's
    botocore import.
    """

    def wrap(func: Callable[..., object]) -> RegisteredTask:
        return shared_task(func, **options)  # type: ignore[no-any-return]

    return wrap


class PipelineCtx(TypedDict):
    """The ONLY payload stages exchange: string ids, never document text."""

    document_id: str
    version_id: str
    tenant_id: str
    sha256: str
    bucket: str
    key: str


class TransientStorageError(Exception):
    """Socket/redis/object-store blip worth a celery autoretry."""


class MalwareDetectedError(Exception):
    """clamd reported a signature; the chain halts and the upload stays quarantined."""

    def __init__(self, signature: str) -> None:
        self.signature = signature
        super().__init__(f"malware signature detected: {signature}")


class ShaMismatchError(Exception):
    """Quarantined bytes hash differently than the recorded sha256."""

    def __init__(self) -> None:
        super().__init__("quarantined bytes do not match recorded sha256")


class _SkipStageError(Exception):
    """Internal: stage produced no work by policy; chain continues."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


_settings_instance: Settings | None = None


def _settings() -> Settings:
    """Process-cached settings; tests monkeypatch this accessor."""
    global _settings_instance
    if _settings_instance is None:
        _settings_instance = Settings()
    return _settings_instance


_LOCAL_ROOT_ENV = "DOCMGMT_LOCAL_STORAGE_ROOT"


def _storage() -> Storage:
    """Backend chosen from settings; local root via env until config wave 2."""
    cfg = _settings()
    if cfg.storage_backend == "local":
        return LocalStorage(
            Path(os.environ.get(_LOCAL_ROOT_ENV, "var/storage")),
            signing_secret=cfg.dev_jwt_secret,
        )
    import boto3  # type: ignore[import-untyped]  # no stubs; s3.py precedent

    scheme = "https" if cfg.minio_secure else "http"
    client = boto3.client(
        "s3",
        endpoint_url=f"{scheme}://{cfg.minio_endpoint}",
        aws_access_key_id=cfg.minio_access_key,
        aws_secret_access_key=cfg.minio_secret_key,
    )
    from app.storage.s3 import S3Storage

    return S3Storage(client, bucket_prefix=cfg.minio_bucket_prefix)


def _journal() -> ProcessingJobsJournal:
    """Journal bound to the process-wide sync session factory."""
    return ProcessingJobsJournal(get_sync_sessions(_settings()))


def _already_succeeded(version_id: uuid.UUID, stage: str) -> bool:
    """#5 guard: state-based short-circuit, answered from processing_jobs."""
    return _journal().has_succeeded(version_id, stage)


def _ids(stage: str, ctx: PipelineCtx) -> dict[str, str]:
    """Log extras carry ids only — never text, findings or matched values."""
    return {
        "stage": stage,
        "document_id": ctx["document_id"],
        "version_id": ctx["version_id"],
    }


T = TypeVar("T")


def _require[T](payload: dict[str, object], key: str, kind: type[T]) -> T:
    """Boundary parse of a derived-artifact field; malformed shapes fail loud."""
    value = payload[key]
    if not isinstance(value, kind):
        msg = f"derived artifact field {key!r} has unexpected type"
        raise TypeError(msg)
    return value


def _read_object(key: str) -> bytes:
    with _storage().open(key) as handle:
        return handle.read()


def _read_derived_json(sha256: str) -> dict[str, object]:
    raw = _read_object(derived_key(sha256, "text.json"))
    parsed: dict[str, object] = json.loads(raw.decode("utf-8"))
    return parsed


def _write_derived_json(sha256: str, payload: dict[str, object]) -> None:
    encoded = json.dumps(payload).encode("utf-8")
    _storage().put(
        derived_key(sha256, "text.json"),
        io.BytesIO(encoded),
        content_type="application/json",
    )


def _promote_to_primary(ctx: PipelineCtx, data: bytes) -> None:
    """Quarantine -> primary promotion: verify, put, record, then delete (#16)."""
    digest = hashlib.sha256(data).hexdigest()
    if digest != ctx["sha256"]:
        raise ShaMismatchError
    key = primary_key(uuid.UUID(ctx["tenant_id"]), digest)
    from app.extraction.sniff import sniff_mime

    mime = sniff_mime(data)
    _storage().put(key, io.BytesIO(data), content_type=mime)
    promote_blob_record(
        _sessions(),
        sha256=digest,
        size_bytes=len(data),
        mime_sniffed=mime,
        bucket_key=key,
        version_id=uuid.UUID(ctx["version_id"]),
    )
    _storage().delete(ctx["key"])
    ctx["key"] = key


def _sessions() -> sessionmaker[Session]:
    """Sync session factory handed to the jobs.py persistence helpers."""
    return get_sync_sessions(_settings())


def _scan_body(ctx: PipelineCtx) -> None:
    cfg = _settings()
    data = _read_object(ctx["key"])
    if not cfg.scan_enabled:
        if cfg.env != "dev":
            # D3: validate_runtime blocks prod startup like this; drift post-startup
            # must equally refuse to continue unscanned (fail closed).
            msg = "SCAN_ENABLED=false outside dev; refusing to continue unscanned"
            raise RuntimeError(msg)
        logger.warning(
            "clamav_unavailable: skipping malware scan (dev fail-open)",
            extra=_ids("scan", ctx),
        )
        raise _SkipStageError("clamav_unavailable")
    try:
        verdict = clamd_scan(CLAMAV_HOST, CLAMAV_PORT, data)
    except ScanError as exc:
        msg = "clamd INSTREAM exchange failed"
        raise TransientStorageError(msg) from exc
    if not verdict.clean:
        raise MalwareDetectedError(verdict.signature or "unknown-signature")
    _promote_to_primary(ctx, data)


def _extract_body(ctx: PipelineCtx) -> None:
    data = _read_object(ctx["key"])
    try:
        extracted = extract_document(data)
    except NeedsOcrError:
        enqueue_ocr.apply_async(args=[dict(ctx)])
        raise
    _write_derived_json(
        ctx["sha256"],
        {
            "text": extracted.text,
            "pages": [{"page_no": page.page_no, "text": page.text} for page in extracted.pages],
            "mime": extracted.mime_sniffed,
            "char_count": extracted.char_count,
            "ocr_used": extracted.ocr_used,
        },
    )


def _keywords_body(ctx: PipelineCtx) -> None:
    payload = _read_derived_json(ctx["sha256"])
    terms = FrequencyFallback().extract(_require(payload, "text", str)).terms
    replace_keywords(
        _sessions(),
        document_id=uuid.UUID(ctx["document_id"]),
        terms=terms,
    )


def _classify_body(ctx: PipelineCtx) -> None:
    payload = _read_derived_json(ctx["sha256"])
    outcome = run_classification(_require(payload, "text", str), Taxonomy.default(), None)
    record_classification(
        _sessions(),
        document_id=uuid.UUID(ctx["document_id"]),
        version_id=uuid.UUID(ctx["version_id"]),
        outcome=outcome,
    )


def _index_body(ctx: PipelineCtx) -> None:
    payload = _read_derived_json(ctx["sha256"])
    upsert_document_text(
        _sessions(),
        version_id=uuid.UUID(ctx["version_id"]),
        body=_require(payload, "text", str),
        char_count=_require(payload, "char_count", int),
        ocr_used=_require(payload, "ocr_used", bool),
    )
    mark_document_ready(_sessions(), document_id=uuid.UUID(ctx["document_id"]))


def _run_stage(
    stage: str,
    ctx: PipelineCtx,
    body: Callable[[], None],
    requires: tuple[str, ...] = (),
) -> PipelineCtx:
    """Guard + journal lifecycle around one stage body; owns the failure map.

    ``requires`` names prerequisite stages that must have SUCCEEDED (state-based,
    #5): after an OCR handoff skips ``extract``, later links must no-op even in
    eager mode, where celery swallows :class:`Ignore` instead of unwinding the
    canvas. On real workers Ignore alone halts the chain; this gate is the
    second line of defence, answered from processing_jobs like every guard.
    """
    journal = _journal()
    version_id = uuid.UUID(ctx["version_id"])
    if _already_succeeded(version_id, stage):
        logger.info("stage_short_circuit", extra=_ids(stage, ctx))
        return ctx
    for prerequisite in requires:
        if not _already_succeeded(version_id, prerequisite):
            logger.info(
                "stage_blocked_by_prerequisite",
                extra={**_ids(stage, ctx), "prerequisite": prerequisite},
            )
            return ctx
    job_row_id = journal.mark_running(uuid.UUID(ctx["document_id"]), version_id, stage)
    try:
        body()
    except _SkipStageError as skip:
        journal.mark_skipped(job_row_id, skip.reason)
        logger.info("stage_skipped", extra={**_ids(stage, ctx), "reason": skip.reason})
        return ctx
    except NeedsOcrError:
        journal.mark_skipped(job_row_id, "needs_tesseract")
        raise Ignore() from None
    except MalwareDetectedError as detected:
        journal.mark_failed(job_row_id, f"malware detected: {detected.signature}")
        raise
    except ShaMismatchError:
        journal.mark_failed(job_row_id, "quarantined bytes do not match recorded sha256")
        raise
    except BlobExistsError:
        journal.mark_failed(job_row_id, "primary blob conflict (#16)")
        raise
    except UnknownMimeError:
        journal.mark_failed(job_row_id, "content matched no known signature")
        raise
    except ValueError, TypeError:
        journal.mark_failed(job_row_id, "unsupported or malformed content")
        raise
    except ParserUnavailable:
        journal.mark_failed(job_row_id, "parser library missing on host")
        raise
    except IntegrityError:
        journal.mark_failed(job_row_id, "write rejected by database integrity guard (#8)")
        raise
    except TransientStorageError:
        journal.mark_failed(job_row_id, f"transient failure in {stage}; retry scheduled")
        raise
    except RuntimeError:
        journal.mark_failed(job_row_id, "configuration refuses this stage (fail-closed)")
        raise
    journal.mark_succeeded(job_row_id)
    logger.info("stage_complete", extra=_ids(stage, ctx))
    return ctx


@pipeline_task(max_retries=3, autoretry_for=(TransientStorageError,))
def scan_for_malware(ctx: PipelineCtx) -> PipelineCtx:
    return _run_stage("scan", ctx, lambda: _scan_body(ctx))


@pipeline_task(max_retries=3, autoretry_for=(TransientStorageError,))
def extract_text(ctx: PipelineCtx) -> PipelineCtx:
    return _run_stage("extract", ctx, lambda: _extract_body(ctx))


@pipeline_task(max_retries=3, autoretry_for=(TransientStorageError,))
def extract_keywords(ctx: PipelineCtx) -> PipelineCtx:
    return _run_stage("keywords", ctx, lambda: _keywords_body(ctx), requires=("extract",))


@pipeline_task(max_retries=3, autoretry_for=(TransientStorageError,))
def embed(ctx: PipelineCtx) -> PipelineCtx:
    # Placeholder: embedding arrives with the model server; document_text.embedding
    # stays NULL and the #6 single-compute contract is preserved for that pass.
    return _run_stage("embed", ctx, lambda: None, requires=("extract",))


@pipeline_task(max_retries=3, autoretry_for=(TransientStorageError,))
def classify(ctx: PipelineCtx) -> PipelineCtx:
    return _run_stage("classify", ctx, lambda: _classify_body(ctx), requires=("extract",))


@pipeline_task(max_retries=3, autoretry_for=(TransientStorageError,))
def build_index(ctx: PipelineCtx) -> PipelineCtx:
    return _run_stage("index", ctx, lambda: _index_body(ctx), requires=("extract",))


@pipeline_task()
def enqueue_ocr(ctx: PipelineCtx) -> None:
    """OCR handoff target on the dedicated queue; Tesseract arrives later wave."""
    _journal().mark_queued(uuid.UUID(ctx["version_id"]), "ocr")
    logger.info("ocr_handoff_queued", extra=_ids("ocr", ctx))


@pipeline_task(max_retries=3, autoretry_for=(TransientStorageError,))
def process_upload_chain(document_id: str, version_id: str, blob_key_or_data_ref: str) -> None:
    """Entry point: resolve ctx from the DB, then fire the fixed chain (#3)."""
    tenant_id, sha256 = load_version_context(
        _sessions(), uuid.UUID(document_id), uuid.UUID(version_id)
    )
    ctx = PipelineCtx(
        document_id=document_id,
        version_id=version_id,
        tenant_id=str(tenant_id),
        sha256=sha256,
        bucket=bucket_name("quarantine"),
        key=blob_key_or_data_ref,
    )
    chain(
        scan_for_malware.s(),
        extract_text.s(),
        extract_keywords.s(),
        embed.s(),
        classify.s(),
        build_index.s(),
    ).apply_async(args=[dict(ctx)])
