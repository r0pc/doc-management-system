"""Typed model for the Kaggle training artifact (schema v1) + compatibility.

Consumes ml/artifact_contract.md verbatim: a joblib payload {"manifest": ...,
"models": {...}} whose manifest carries schema_version / sklearn_version /
embedding_model_id / dim / labels / metrics. Compatibility checking is pure
except the sklearn runtime probe, which degrades to a warning when
scikit-learn is absent (host/dev venvs ship without the ML stack by design —
self-hosting invariant; nothing is pulled in at import time).
"""

from __future__ import annotations

import importlib.util
from collections.abc import Mapping, Sequence
from collections.abc import Set as AbstractSet
from typing import Final

from pydantic import BaseModel

SCHEMA_VERSION: Final[int] = 1
EXPECTED_DIM: Final[int] = 384
EMBEDDING_MODEL_ID: Final[str] = "BAAI/bge-small-en-v1.5"

DOC_TYPE_LABELS: Final[frozenset[str]] = frozenset(
    {
        "contract",
        "vendor_msa",
        "invoice",
        "hr_letter",
        "disciplinary_notice",
        "monthly_report",
        "policy_memo",
    }
)
SECURITY_LEVEL_LABELS: Final[frozenset[str]] = frozenset(
    {"Public", "Internal", "Confidential", "Restricted"}
)

#: Model label (a training slug) -> the ``doc_types.name`` it denotes.
#:
#: The heads emit slugs from ml/templates.py; the persisted taxonomy is the
#: ``doc_types`` tree seeded by migration 0003 and edited by admins thereafter.
#: This map is a pure NAME translation, never a row factory: resolution looks
#: the name up and yields NULL + a log line when no row exists (see
#: app.workers.jobs.resolve_doc_type_id). Model output must not be able to
#: mint taxonomy rows — a drifted or swapped artifact would then rewrite the
#: tenant's document-type vocabulary as a side effect of ingestion.
#:
#: ``hr_letter`` is deliberately mapped to a name migration 0003 does NOT seed.
#: The seed's ``HR`` node is the parent CATEGORY of ``Disciplinary Notice``, not
#: a letter type; silently coarsening a leaf prediction onto its parent would
#: record a type the model never predicted. Until an admin creates "HR Letter"
#: under "HR" via the taxonomy CRUD, those predictions resolve to NULL and log.
DOC_TYPE_LABEL_TO_TAXONOMY_NAME: Final[Mapping[str, str]] = {
    "contract": "Contract",
    "vendor_msa": "Vendor MSA",
    "invoice": "Invoice",
    "hr_letter": "HR Letter",
    "disciplinary_notice": "Disciplinary Notice",
    "monthly_report": "Monthly Report",
    "policy_memo": "Policy Memo",
}


def taxonomy_name_for_label(label: str) -> str | None:
    """``doc_types.name`` a model label denotes; None when the label is unknown."""
    return DOC_TYPE_LABEL_TO_TAXONOMY_NAME.get(label)


_LABEL_GROUPS: Final[tuple[str, str]] = ("doc_type", "security_level")
_WARNING_PREFIX: Final[str] = "warning:"


class ArtifactManifest(BaseModel):
    """The manifest half of model.joblib (artifact_contract.md schema v1)."""

    schema_version: int
    sklearn_version: str
    embedding_model_id: str
    dim: int
    labels: dict[str, list[str]]
    metrics: dict[str, object]


def _sklearn_major_minor(version: str) -> tuple[str, ...]:
    """('major', 'minor') of a version string, or () when unparseable."""
    parts = version.split(".")
    return tuple(parts[:2]) if len(parts) >= 2 else ()


def _sklearn_compatibility(manifest_version: str) -> list[str]:
    """Contract rule 2: major.minor must equal the runtime's; patches tolerated.

    The sklearn import is lazy and guarded: when scikit-learn is not installed
    on this host the check degrades to a 'warning:' entry instead of an error,
    so hosts without the ML stack can still accept an artifact they cannot
    fully verify locally.
    """
    manifest_mm = _sklearn_major_minor(manifest_version)
    if len(manifest_mm) != 2:
        return [f"manifest sklearn_version {manifest_version!r} is not <major>.<minor>[.<patch>]"]
    if importlib.util.find_spec("sklearn") is None:
        return [
            f"{_WARNING_PREFIX} scikit-learn is not installed on this host; "
            f"manifest sklearn_version {manifest_version!r} could not be verified"
        ]
    module = importlib.import_module("sklearn")
    runtime_mm = _sklearn_major_minor(str(getattr(module, "__version__", "")))
    if runtime_mm != manifest_mm:
        runtime = ".".join(runtime_mm) if runtime_mm else "unknown"
        return [
            f"sklearn major.minor mismatch: manifest {'.'.join(manifest_mm)} vs runtime {runtime}"
        ]
    return []


def _label_errors(
    labels: dict[str, list[str]],
    taxonomy_labels: tuple[AbstractSet[str], AbstractSet[str]],
) -> list[str]:
    """Contract rule 4: every label must be a member of the backend taxonomy."""
    errors: list[str] = []
    for group, allowed in zip(_LABEL_GROUPS, taxonomy_labels, strict=True):
        if group not in labels:
            errors.append(f"labels missing required group {group!r}")
            continue
        unknown = sorted(set(labels[group]) - allowed)
        if unknown:
            errors.append(f"labels.{group} outside taxonomy: {unknown}")
    unexpected = sorted(set(labels) - set(_LABEL_GROUPS))
    if unexpected:
        errors.append(f"unexpected label groups: {unexpected}")
    return errors


def validate_manifest(
    manifest: ArtifactManifest,
    dim_expected: int = EXPECTED_DIM,
    taxonomy_labels: tuple[AbstractSet[str], AbstractSet[str]] = (
        DOC_TYPE_LABELS,
        SECURITY_LEVEL_LABELS,
    ),
) -> list[str]:
    """Compatibility rules 1-5 of artifact_contract.md as error strings.

    Hard errors block loading. Entries prefixed ``warning:`` are tolerated
    (recorded for the log) — currently only the sklearn-runtime-unavailable
    case. Rule 5 (metrics shape, restricted_recall gate) is operational and
    intentionally not enforced here.
    """
    errors: list[str] = []
    if manifest.schema_version != SCHEMA_VERSION:
        errors.append(
            f"unsupported schema_version {manifest.schema_version}; expected {SCHEMA_VERSION}"
        )
    if manifest.embedding_model_id != EMBEDDING_MODEL_ID:
        errors.append(
            f"embedding_model_id {manifest.embedding_model_id!r} != {EMBEDDING_MODEL_ID!r}"
        )
    if manifest.dim != dim_expected:
        errors.append(f"dim {manifest.dim} != expected {dim_expected}")
    errors.extend(_sklearn_compatibility(manifest.sklearn_version))
    errors.extend(_label_errors(manifest.labels, taxonomy_labels))
    return errors


def hard_errors(errors: Sequence[str]) -> list[str]:
    """Split validation output into blocking errors (warnings filtered out)."""
    return [error for error in errors if not error.startswith(_WARNING_PREFIX)]
