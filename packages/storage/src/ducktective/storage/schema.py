import asyncio
from pathlib import (
    Path,
)

from alembic import (
    command,
)
from alembic.config import (
    Config,
)
from alembic.script import (
    ScriptDirectory,
)
from sqlalchemy import (
    text,
)
from sqlalchemy.exc import (
    ProgrammingError,
)
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
)


MIGRATIONS_DIRECTORY = Path(__file__).resolve().parents[3] / "migrations"
"""Каталог миграций лежит рядом с пакетом, а не внутри него: alembic ищет
его по `alembic.ini`, и у службы, запущенной из другого каталога, этого файла
под рукой нет. Путь считается от модуля, а не от рабочего каталога."""

MIGRATION_LOCK_KEY = 0x4475636B
"""Ключ рекомендательного замка Postgres: «Duck» в кодах символов. Один на
установку — замок и нужен, чтобы миграцию катил один процесс из трёх."""


class SchemaOutdatedError(RuntimeError):
    """База отстала от кода, а накатывать миграции самому не велено."""

    def __init__(self, current: str | None, head: str) -> None:
        super().__init__(
            f"Схема базы на ревизии {current or 'пусто'}, код ждёт {head}: "
            "выполните `uv run alembic upgrade head` или включите DATABASE_AUTO_MIGRATE"
        )
        self.current = current
        self.head = head


def head_revision() -> str:
    script = ScriptDirectory.from_config(_config(""))
    head = script.get_current_head()
    if head is None:
        raise RuntimeError(f"В {MIGRATIONS_DIRECTORY} нет ни одной миграции")
    return head


async def current_revision(engine: AsyncEngine) -> str | None:
    """Ревизия базы; `None` — миграции ещё не катились вовсе."""
    async with engine.connect() as connection:
        try:
            row = await connection.execute(text("select version_num from alembic_version"))
        except ProgrammingError:
            return None
        return row.scalar_one_or_none()


async def ensure_schema(engine: AsyncEngine, *, database_url: str, auto_migrate: bool) -> None:
    """Сверяет базу с миграциями до того, как служба примет первый запрос.

    Отставшая база иначе выясняется по 500 на каждый запрос: колонки нет, а
    список дел «пропал». Служба, которая не стартует и называет ревизии,
    честнее службы, которая стартует и молча отдаёт пустоту.

    Накат идёт под рекомендательным замком Postgres: api и оба воркера
    стартуют одновременно, и без замка три `upgrade head` столкнулись бы на
    одной таблице. Кто взял замок первым — катит; остальные дожидаются и,
    получив замок, видят уже готовую схему.
    """
    head = head_revision()
    current = await current_revision(engine)
    if current == head:
        return
    if not auto_migrate:
        raise SchemaOutdatedError(current, head)

    async with engine.connect() as connection:
        await connection.execute(text("select pg_advisory_lock(:key)"), {"key": MIGRATION_LOCK_KEY})
        try:
            if await current_revision(engine) != head:
                await asyncio.to_thread(command.upgrade, _config(database_url), "head")
        finally:
            await connection.execute(
                text("select pg_advisory_unlock(:key)"), {"key": MIGRATION_LOCK_KEY}
            )


def _config(database_url: str) -> Config:
    """Настройка alembic без `alembic.ini`: путь к миграциям и адрес базы.

    Адрес передаётся сюда, а не через окружение: служба уже прочитала его
    из своих настроек, и подсовывать его в `os.environ` ради `env.py` значило
    бы менять окружение процесса из-за одной команды.
    """
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS_DIRECTORY))
    if database_url:
        config.set_main_option("sqlalchemy.url", database_url)
    return config
