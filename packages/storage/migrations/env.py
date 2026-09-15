import asyncio
import os
from logging.config import (
    fileConfig,
)

from alembic import (
    context,
)
from dotenv import (
    find_dotenv,
    load_dotenv,
)
from sqlalchemy import (
    Connection,
    pool,
)
from sqlalchemy.ext.asyncio import (
    async_engine_from_config,
)

from ducktective.storage.models import (
    Base,
)


config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _database_url() -> str:
    """Адрес базы для миграций.

    `.env` читается здесь, потому что миграции запускаются не приложением:
    у него настройки собирает pydantic-settings, а у alembic своя точка входа,
    и без этого `alembic upgrade head` падал там, где `ducktective serve`
    поднимался — на одной и той же машине с одним и тем же файлом.

    Файл не перекрывает окружение: заданный снаружи адрес — это осознанный
    выбор развёртывания, и локальный `.env` не должен его молча отменять.

    Адрес из конфигурации alembic старше обоих: его задаёт служба, катящая
    миграции при старте, — она уже знает свою базу и не ходит за ней в файл.
    """
    configured = config.get_main_option("sqlalchemy.url")
    if configured:
        return configured

    load_dotenv(find_dotenv(usecwd=True))

    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError(
            "Не задан DATABASE_URL — ни в окружении, ни в .env каталога, "
            "из которого запущен alembic"
        )
    return url


def run_migrations_offline() -> None:
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def _run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = _database_url()

    engine = async_engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with engine.connect() as connection:
        await connection.run_sync(_run_migrations)

    await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
