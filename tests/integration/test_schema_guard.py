import asyncio
import os

import pytest
from alembic import (
    command,
)
from alembic.config import (
    Config,
)

from ducktective.storage.database import (
    build_engine,
)
from ducktective.storage.schema import (
    MIGRATIONS_DIRECTORY,
    SchemaOutdatedError,
    current_revision,
    ensure_schema,
    head_revision,
)


pytestmark = pytest.mark.integration


def _step_back(database_url: str) -> None:
    """Откатывает базу на одну ревизию: так выглядит база после `git pull`.

    Вызывается из потока: `env.py` заводит свой цикл событий, а внутри
    цикла теста второй не запускается.
    """
    previous = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = database_url
    try:
        config = Config()
        config.set_main_option("script_location", str(MIGRATIONS_DIRECTORY))
        command.downgrade(config, "-1")
    finally:
        if previous is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous


async def test_outdated_schema_stops_the_service_when_auto_migrate_is_off(
    migrated_database_url: str,
) -> None:
    """Служба, которая не стартует и называет ревизии, честнее 500 на каждый запрос."""
    engine = build_engine(migrated_database_url)
    try:
        await asyncio.to_thread(_step_back, migrated_database_url)
        assert await current_revision(engine) != head_revision()

        with pytest.raises(SchemaOutdatedError) as caught:
            await ensure_schema(engine, database_url=migrated_database_url, auto_migrate=False)
        assert caught.value.head == head_revision()

        await ensure_schema(engine, database_url=migrated_database_url, auto_migrate=True)
        assert await current_revision(engine) == head_revision()
    finally:
        await engine.dispose()


async def test_schema_at_head_is_left_alone(migrated_database_url: str) -> None:
    engine = build_engine(migrated_database_url)
    try:
        await ensure_schema(engine, database_url=migrated_database_url, auto_migrate=False)
        assert await current_revision(engine) == head_revision()
    finally:
        await engine.dispose()
