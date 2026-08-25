"""Pure domain value objects for the Secure DMS.

Single source of truth imported by both the API and the workers. This module
must stay free of any framework import (no web, no ORM, no I/O) so the
authorisation suite can run as a parametrised table with no fixtures.
"""

import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from types import MappingProxyType
from typing import Final


class LevelName(StrEnum):
    """Security levels, ordered weakest to strongest."""

    PUBLIC = "public"
    INTERNAL = "internal"
    CONFIDENTIAL = "confidential"
    RESTRICTED = "restricted"


LEVEL_RANK: Final[Mapping[LevelName, int]] = MappingProxyType(
    {
        LevelName.PUBLIC: 1,
        LevelName.INTERNAL: 2,
        LevelName.CONFIDENTIAL: 3,
        LevelName.RESTRICTED: 4,
    }
)

# Invariant #9: nothing matched defaults to Internal, never Public — absence of
# evidence defaults UP.
DEFAULT_FLOOR_RANK: Final[int] = LEVEL_RANK[LevelName.INTERNAL]


@dataclass(frozen=True)
class Finding:
    """One recogniser hit.

    Character offsets only — invariant #12 forbids copying matched text into
    secondary storage, so a Finding never carries the sensitive value itself.
    """

    entity_type: str
    rule_id: str
    page_no: int | None
    char_start: int
    char_end: int
    score: float


@dataclass(frozen=True)
class UserCtx:
    """Authenticated caller as seen by authorisation checks."""

    tenant_id: uuid.UUID
    department_id: uuid.UUID | None
    clearance_rank: int
    role: str
    sub: str
    visible_department_ids: tuple[uuid.UUID, ...] = ()


@dataclass(frozen=True)
class DocumentRef:
    """The document attributes authorisation is gated on.

    Permission lives on the documents row (invariant #15); this ref carries no
    object key because an object key is never an authorisation boundary.
    """

    id: uuid.UUID
    tenant_id: uuid.UUID
    department_id: uuid.UUID | None
    level_rank: int
    deleted_at: datetime | None


class Action(StrEnum):
    """Operations callers may attempt; each maps to a distinct permission."""

    UPLOAD = "upload"
    VIEW = "view"
    DOWNLOAD = "download"
    PREVIEW = "preview"
    RECLASSIFY = "reclassify"
    RESOLVE_REVIEW = "resolve_review"
    MANAGE_TAXONOMY = "manage_taxonomy"
    VIEW_AUDIT = "view_audit"
