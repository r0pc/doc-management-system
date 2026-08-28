"""Repository boundary contract.

ORM rows never cross the repository boundary outward: callers receive domain
objects (or scalars), never ``Base`` subclasses. SQLAlchemy rows are confined
to ``db/`` per the project layout rules - repositories are the translation
seam, which keeps policy code pure and free of session/ORM concerns.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import DeclarativeBase


class BaseRepository[ModelT: DeclarativeBase]:
    """Holds the session only; query methods live on concrete subclasses."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
