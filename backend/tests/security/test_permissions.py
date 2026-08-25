"""Exact role x action permission grid (preview != download; fail-closed on unknown roles)."""

import pytest

from app.domain.models import Action
from app.security.permissions import ROLE_ACTIONS, role_can

EXPECTED_MATRIX: dict[str, frozenset[Action]] = {
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
        }
    ),
    "dept_manager": frozenset(
        {Action.UPLOAD, Action.VIEW, Action.DOWNLOAD, Action.PREVIEW, Action.RESOLVE_REVIEW}
    ),
    "employee": frozenset({Action.UPLOAD, Action.VIEW, Action.DOWNLOAD, Action.PREVIEW}),
    "viewer": frozenset({Action.VIEW, Action.PREVIEW}),
}

GRID = [
    (role, action)  #
    for role, granted in EXPECTED_MATRIX.items()
    for action in Action
]


def test_role_table_covers_exactly_the_five_known_roles() -> None:
    assert set(ROLE_ACTIONS) == set(EXPECTED_MATRIX)


def test_every_role_entry_is_frozen() -> None:
    assert all(isinstance(actions, frozenset) for actions in ROLE_ACTIONS.values())


@pytest.mark.parametrize(("role", "action"), GRID)
def test_grid_grants_exactly_the_expected_actions(role: str, action: Action) -> None:
    assert role_can(role, action) is (action in EXPECTED_MATRIX[role])


def test_admin_holds_every_action() -> None:
    assert ROLE_ACTIONS["admin"] == frozenset(Action)


def test_viewer_can_preview_but_never_download() -> None:
    assert role_can("viewer", Action.PREVIEW) is True
    assert role_can("viewer", Action.DOWNLOAD) is False


def test_employee_is_denied_elevated_actions() -> None:
    for denied in (
        Action.RECLASSIFY,
        Action.RESOLVE_REVIEW,
        Action.VIEW_AUDIT,
        Action.MANAGE_TAXONOMY,
    ):
        assert role_can("employee", denied) is False


@pytest.mark.parametrize("unknown_role", ["ghost", "", "Admin", "superuser"])
def test_unknown_roles_fail_closed(unknown_role: str) -> None:
    assert role_can(unknown_role, Action.VIEW) is False
