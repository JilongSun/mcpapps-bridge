"""Async SQLAlchemy engine and migration helpers."""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from anyio import to_thread
from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


class SqliteDatabase:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.url = f"sqlite+aiosqlite:///{path.as_posix()}"
        self.engine: AsyncEngine = create_async_engine(self.url)
        event.listen(self.engine.sync_engine, "connect", _enable_sqlite_foreign_keys)
        self.session_factory = async_sessionmaker(
            self.engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )

    async def migrate(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        await to_thread.run_sync(self._upgrade_to_head)

    async def close(self) -> None:
        await self.engine.dispose()

    def _upgrade_to_head(self) -> None:
        config = Config()
        config.set_main_option("script_location", str(_migration_root()))
        config.set_main_option("sqlalchemy.url", self.url)
        command.upgrade(config, "head")


def _enable_sqlite_foreign_keys(dbapi_connection: object, _connection_record: object) -> None:
    cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
    try:
        cursor.execute("PRAGMA foreign_keys=ON")
    finally:
        cursor.close()


def _migration_root() -> Path:
    packaged = Path(__file__).with_name("migrations")
    if packaged.is_dir():
        return packaged
    return Path(__file__).resolve().parents[3] / "migrations"
