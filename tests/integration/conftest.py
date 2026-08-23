import asyncio
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
from sqlalchemy import (
    text,
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

APP_ROLE = "ducktective_app"
APP_PASSWORD = "ducktective_app"

PREPARE_STATEMENTS = (
    "create extension if not exists vector",
    "create extension if not exists pg_trgm",
    f"create role {APP_ROLE} with login password '{APP_PASSWORD}' "
    "nosuperuser nocreatedb nocreaterole nobypassrls",
    f"grant all on schema public to {APP_ROLE}",
    f"alter schema public owner to {APP_ROLE}",
)


@pytest.fixture(scope="session")
def migrated_database_url() -> Iterator[str]:
    """Поднимает Postgres с pgvector и накатывает все миграции.

    Прогон реальных миграций — часть проверки: он ловит расхождения между
    ORM-моделями и версиями схемы, которых не видят тесты на фейках.
    """
    with PostgresContainer("pgvector/pgvector:pg17", driver="asyncpg") as container:
        superuser_url = container.get_connection_url()
        database_url = _as_application_role(superuser_url)
        _prepare_database(superuser_url)
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


def _as_application_role(superuser_url: str) -> str:
    """Тот же адрес, но под ролью приложения.

    Миграции и сессии идут под ней обе: политики объявлены с `force`, то есть
    действуют и на владельца таблиц, а под суперпользователем не действуют
    вовсе — он обходит row level security по определению. Прогон тестов
    суперпользователем показывал бы зелёное там, где изоляции нет.
    """
    _, _, tail = superuser_url.partition("://")
    _, _, host_and_database = tail.partition("@")
    return f"postgresql+asyncpg://{APP_ROLE}:{APP_PASSWORD}@{host_and_database}"


def _prepare_database(superuser_url: str) -> None:
    """Готовит базу тем, на что у роли приложения нет прав.

    Расширения ставит суперпользователь: `create extension` обычной роли
    недоступен, а миграция `0001` его требует.
    """
    asyncio.run(_run_as_superuser(superuser_url))


async def _run_as_superuser(superuser_url: str) -> None:
    engine = build_engine(superuser_url, pool_size=1, max_overflow=0)
    try:
        async with engine.begin() as connection:
            for statement in PREPARE_STATEMENTS:
                await connection.execute(text(statement))
    finally:
        await engine.dispose()
