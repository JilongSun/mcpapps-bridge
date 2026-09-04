"""Shared SQLAlchemy metadata for the server-owned SQLite adapter.

All topology, session, event, and snapshot rows use this registry so Alembic sees one complete
schema. Application contracts never inherit from these infrastructure models.
"""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass
