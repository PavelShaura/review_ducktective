import os
from collections.abc import (
    AsyncIterator,
    Iterator,
)
from pathlib import (
    Path,
)

import pytest
from alembic import (
    command,
)
from alembic.config import (
    Config,
)
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
)
from testcontainers.community.postgres import (
    PostgresContainer,
)

from ducktective.storage.database import (
    build_engine,
    build_session_factory,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="session")
def migrated_database_url() -> Iterator[str]:
    """Поднимает Postgres с pgvector и накатывает все миграции.

    Прогон реальных миграций — часть проверки: он ловит расхождения между
    ORM-моделями и версиями схемы, которых не видят тесты на фейках.
    """
    with PostgresContainer("pgvector/pgvector:pg17", driver="asyncpg") as container:
        database_url = container.get_connection_url()
        previous_url = os.environ.get("DATABASE_URL")
        os.environ["DATABASE_URL"] = database_url

        alembic_config = Config(str(PROJECT_ROOT / "alembic.ini"))
        alembic_config.set_main_option(
            "script_location",
            str(PROJECT_ROOT / "packages" / "storage" / "migrations"),
        )
        command.upgrade(alembic_config, "head")

        try:
            yield database_url
        finally:
            if previous_url is None:
                os.environ.pop("DATABASE_URL", None)
            else:
                os.environ["DATABASE_URL"] = previous_url


@pytest.fixture
async def session_factory(
    migrated_database_url: str,
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = build_engine(migrated_database_url, pool_size=2, max_overflow=0)
    try:
        yield build_session_factory(engine)
    finally:
        await engine.dispose()
