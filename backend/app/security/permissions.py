"""Role-to-action permission table.

Server-side source of truth for authorisation decisions (client-side checks
are cosmetic). Preview and download are deliberately distinct actions: seeing
a document on screen never implies the right to a copyable original.
"""

from __future__ import annotations

from typing import Final

from app.domain.models import Action

ROLE_ACTIONS: Final[dict[str, frozenset[Action]]] = {
    "admin": frozenset(Action),
    "security_officer": frozenset(
        {
            Action.UPLOAD,
            Action.VIEW,
            Action.DOWNLOAD,
            Action.PREVIEW,
            Action.RECLASSIFY,
            Action.RESOLVE_REVIEW,
            Action.VIEW_AUDIT,
            Action.DELETE,
        }
    ),
    "dept_manager": frozenset(
        {Action.UPLOAD, Action.VIEW, Action.DOWNLOAD, Action.PREVIEW, Action.RESOLVE_REVIEW}
    ),
    "employee": frozenset({Action.UPLOAD, Action.VIEW, Action.DOWNLOAD, Action.PREVIEW}),
    "viewer": frozenset({Action.VIEW, Action.PREVIEW}),
}


def role_can(role: str, action: Action) -> bool:
    """Return whether ``role`` may perform ``action``; unknown roles fail closed."""
    return action in ROLE_ACTIONS.get(role, frozenset())
