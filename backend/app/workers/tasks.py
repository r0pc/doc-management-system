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

from __future__ import annotations

import hashlib
import io
import json
import logging
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Protocol, TypedDict, TypeVar

from celery import chain
from celery.exceptions import Ignore
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.classification.ml.loader import MlArtifact, embed_text, get_artifact
from app.classification.pipeline import classify as run_classification
from app.classification.pipeline import ml_threshold_from_env
from app.config import Settings, resolve_storage_root
from app.domain.taxonomy import Taxonomy
from app.extraction.base import NeedsOcrError, ParserUnavailable, UnknownMimeError
from app.extraction.keywords import FrequencyFallback
from app.extraction.registry import extract_document
from app.storage.base import BlobExistsError, Storage
from app.storage.keys import bucket_name, derived_key, primary_key, quarantine_key
from app.storage.local import LocalStorage
from app.workers.celery_app import celery_app
from app.workers.jobs import (
    ProcessingJobsJournal,
    get_sync_sessions,
    load_version_context,
    mark_document_failed,
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

    def delay(self, *args: object, **kwargs: object) -> object: ...

    def apply_async(
        self,
        *,
        args: list[object] | None = None,
        kwargs: dict[str, object] | None = None,
        **options: object,
    ) -> object: ...


def pipeline_task(**options: object) -> Callable[[Callable[..., object]], RegisteredTask]:
    """Typed passthrough that binds each task to THIS app, explicitly.

    Not ``shared_task``: that binds lazily to whatever Celery app happens to be
    current when the decorator runs. The worker starts via
    ``-A app.workers.celery_app``, so the app exists there — but the API only
    reaches this module through a function-local import inside
    ``_enqueue_chain``, with nothing having imported ``celery_app`` first. The
    tasks then bound to Celery's *default* app, whose broker is unset, and
    every ``.delay()`` from the API dialled the amqp://localhost:5672 fallback
    and failed with ECONNREFUSED — surfacing as a 503 on upload completion
    while the worker itself was connected and healthy.

    Binding to the imported app removes the dependence on import order.

    celery ships no type stubs (pyproject ignores the missing imports); this
    adapter keeps every task body strictly checked while isolating the untyped
    boundary to one line — the same narrow-exception policy as app/storage/s3.py's
    botocore import.
    """

    def wrap(func: Callable[..., object]) -> RegisteredTask:
        return celery_app.task(func, **options)  # type: ignore[no-any-return]

    return wrap


class PipelineCtx(TypedDict):
    """The ONLY payload stages exchange: string ids, never document text."""

    document_id: str
    version_id: str
    tenant_id: str
    # NULL until the pipeline reads the bytes: the API signs an upload intent
    # without ever seeing content (#1), so content identity is established by
    # _ensure_sha256 during scan/extract, not at intent time.
    sha256: str | None
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


def _storage() -> Storage:
    """Backend chosen from settings; local root anchored to repo root."""
    cfg = _settings()
    if cfg.storage_backend == "local":
        root = resolve_storage_root()
        return LocalStorage(
            root,
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


def _require_sha256(ctx: PipelineCtx) -> str:
    """Digest for a post-extract stage; absence is a contract breach, not data.

    Stages after extract can only run once ``_ensure_sha256`` has stamped the
    ctx, so a None here means the chain was entered out of order rather than
    that the document was malformed — fail loud instead of keying a derived
    lookup on None.
    """
    sha256 = ctx["sha256"]
    if sha256 is None:
        msg = "pipeline ctx reached a post-extract stage without a content digest"
        raise RuntimeError(msg)
    return sha256


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


def _ensure_sha256(ctx: PipelineCtx, data: bytes) -> str:
    """Establish (once) the content identity every derived key hangs off.

    The API never sees the bytes (#1), so ``document_versions.blob_sha256`` is
    NULL at intent time and the pipeline is what establishes content identity.
    Populating ctx here — not only on the promotion path, which the dev
    fail-open scan gate skips — is what keeps ``derived_key`` resolvable and
    the #5 idempotency guard content-addressed for every stage downstream.
    A digest already on the ctx is authoritative: disagreement means the
    quarantined bytes changed under us.
    """
    digest = hashlib.sha256(data).hexdigest()
    recorded = ctx["sha256"]
    if recorded is not None and recorded != digest:
        raise ShaMismatchError
    ctx["sha256"] = digest
    return digest


def _promote_to_primary(ctx: PipelineCtx, data: bytes) -> None:
    """Quarantine -> primary promotion: verify, put, record, then delete (#16)."""
    digest = _ensure_sha256(ctx, data)
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
        _promote_to_primary(ctx, data)
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
    # Scan promotes and stamps the digest, but the dev fail-open gate can skip
    # that stage entirely; derived keys must resolve either way.
    sha256 = _ensure_sha256(ctx, data)
    try:
        extracted = extract_document(data)
    except NeedsOcrError:
        enqueue_ocr.apply_async(args=[dict(ctx)])
        raise
    _write_derived_json(
        sha256,
        {
            "text": extracted.text,
            "pages": [{"page_no": page.page_no, "text": page.text} for page in extracted.pages],
            "mime": extracted.mime_sniffed,
            "char_count": extracted.char_count,
            "ocr_used": extracted.ocr_used,
        },
    )


def _keywords_body(ctx: PipelineCtx) -> None:
    payload = _read_derived_json(_require_sha256(ctx))
    terms = FrequencyFallback().extract(_require(payload, "text", str)).terms
    replace_keywords(
        _sessions(),
        document_id=uuid.UUID(ctx["document_id"]),
        terms=terms,
    )


def _artifact() -> MlArtifact | None:
    """The process-cached model artifact at the configured path (None is normal)."""
    return get_artifact(Path(_settings().model_artifact_path))


def _derived_embedding(payload: dict[str, object]) -> list[float] | None:
    """The embed stage's vector off the derived artifact, if it ran and worked."""
    stored = payload.get("embedding")
    if not isinstance(stored, list):
        return None
    return [float(value) for value in stored]


def _embed_body(ctx: PipelineCtx) -> None:
    """THE forward pass over this document (#6).

    The vector lands on the derived artifact and is read back by BOTH classify
    (as ``embedding=``) and index (into ``document_text.embedding`` for the
    pgvector arm). No later stage may encode this text again.
    """
    payload = _read_derived_json(_require_sha256(ctx))
    vector = embed_text(_artifact(), _require(payload, "text", str))
    if vector is None:
        logger.info("embed_unavailable", extra=_ids("embed", ctx))
        return
    payload["embedding"] = vector
    _write_derived_json(_require_sha256(ctx), payload)


def _classify_body(ctx: PipelineCtx) -> None:
    payload = _read_derived_json(_require_sha256(ctx))
    outcome = run_classification(
        _require(payload, "text", str),
        Taxonomy.default(),
        _artifact(),
        ml_threshold=ml_threshold_from_env(),
        # Reuse of the embed stage's vector; re-encoding here would be a second
        # pass over the same text with the same model, i.e. a bug (#6).
        embedding=_derived_embedding(payload),
    )
    record_classification(
        _sessions(),
        document_id=uuid.UUID(ctx["document_id"]),
        version_id=uuid.UUID(ctx["version_id"]),
        outcome=outcome,
    )


def _index_body(ctx: PipelineCtx) -> None:
    payload = _read_derived_json(_require_sha256(ctx))
    embedding = payload.get("embedding")
    upsert_document_text(
        _sessions(),
        version_id=uuid.UUID(ctx["version_id"]),
        body=_require(payload, "text", str),
        char_count=_require(payload, "char_count", int),
        ocr_used=_require(payload, "ocr_used", bool),
        embedding=embedding if isinstance(embedding, list) else None,
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
        # The chain halts here for good: flip the document out of 'processing'
        # so the halt is visible on the documents row itself (#4).
        mark_document_failed(_sessions(), document_id=uuid.UUID(ctx["document_id"]))
        raise
    except ShaMismatchError:
        journal.mark_failed(job_row_id, "quarantined bytes do not match recorded sha256")
        mark_document_failed(_sessions(), document_id=uuid.UUID(ctx["document_id"]))
        raise
    except BlobExistsError:
        journal.mark_failed(job_row_id, "primary blob conflict (#16)")
        mark_document_failed(_sessions(), document_id=uuid.UUID(ctx["document_id"]))
        raise
    except UnknownMimeError:
        journal.mark_failed(job_row_id, "content matched no known signature")
        mark_document_failed(_sessions(), document_id=uuid.UUID(ctx["document_id"]))
        raise
    # Parenthesised deliberately: PEP 758 allows the bare form, but only from
    # Python 3.14, and this package declares requires-python >= 3.12 and ships
    # on a 3.12 base image. The bare form parses on the 3.14 dev host and
    # SyntaxErrors at import inside the container.
    except (ValueError, TypeError):
        journal.mark_failed(job_row_id, "unsupported or malformed content")
        mark_document_failed(_sessions(), document_id=uuid.UUID(ctx["document_id"]))
        raise
    except ParserUnavailable:
        journal.mark_failed(job_row_id, "parser library missing on host")
        mark_document_failed(_sessions(), document_id=uuid.UUID(ctx["document_id"]))
        raise
    except IntegrityError:
        journal.mark_failed(job_row_id, "write rejected by database integrity guard (#8)")
        mark_document_failed(_sessions(), document_id=uuid.UUID(ctx["document_id"]))
        raise
    except TransientStorageError:
        journal.mark_failed(job_row_id, f"transient failure in {stage}; retry scheduled")
        raise
    except RuntimeError:
        journal.mark_failed(job_row_id, "configuration refuses this stage (fail-closed)")
        mark_document_failed(_sessions(), document_id=uuid.UUID(ctx["document_id"]))
        raise
    except Exception as unexpected:
        # #4 backstop. The ladder above names every failure we can classify;
        # anything else still has to leave the pipeline answerable from SQL.
        # Without this, an unlisted exception unwinds past the journal and pins
        # the job at 'running' and the document at 'processing' forever.
        #
        # The reason is the exception TYPE only. Exception payloads routinely
        # carry document content (parser errors quote the offending bytes), and
        # the journal is read back into the UI — safety rail: never log or
        # persist document text.
        journal.mark_failed(job_row_id, f"unexpected {type(unexpected).__name__} in {stage}")
        mark_document_failed(_sessions(), document_id=uuid.UUID(ctx["document_id"]))
        logger.exception("stage_unexpected_failure", extra=_ids(stage, ctx))
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
    return _run_stage("embed", ctx, lambda: _embed_body(ctx), requires=("extract",))


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
def process_upload_chain(
    document_id: str, version_id: str, blob_key_or_data_ref: str | None = None
) -> None:
    """Entry point: resolve ctx from the DB, then fire the fixed chain (#3)."""
    tenant_id, sha256 = load_version_context(
        _sessions(), uuid.UUID(document_id), uuid.UUID(version_id)
    )
    if blob_key_or_data_ref is None:
        blob_key_or_data_ref = quarantine_key(tenant_id, uuid.UUID(document_id))
    ctx = PipelineCtx(
        document_id=document_id,
        version_id=version_id,
        tenant_id=str(tenant_id),
        sha256=sha256,
        bucket=bucket_name("quarantine"),
        key=blob_key_or_data_ref,
    )
    if celery_app.conf.task_always_eager:
        curr_ctx: dict[str, object] = dict(ctx)
        for stage_fn in (
            scan_for_malware,
            extract_text,
            extract_keywords,
            embed,
            classify,
            build_index,
        ):
            res = stage_fn(curr_ctx)
            if isinstance(res, dict):
                curr_ctx = res
    else:
        chain(
            scan_for_malware.s(),
            extract_text.s(),
            extract_keywords.s(),
            embed.s(),
            classify.s(),
            build_index.s(),
        ).apply_async(args=[dict(ctx)])
