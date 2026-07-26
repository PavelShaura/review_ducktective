from datetime import (
    datetime,
)

from sqlalchemy import (
    DateTime,
    MetaData,
)
from sqlalchemy.orm import (
    DeclarativeBase,
)


NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Базовый класс ORM-моделей.

    Соглашение об именовании ограничений задано явно: без него autogenerate
    в Alembic порождает имена, зависящие от диалекта, и миграции перестают
    воспроизводиться.

    Все datetime-колонки хранятся с часовым поясом: домен оперирует aware-временем
    в UTC, и naive-колонка приводит к ошибке на уровне драйвера.
    """

    metadata = MetaData(naming_convention=NAMING_CONVENTION)
    type_annotation_map = {  # noqa: RUF012
        datetime: DateTime(timezone=True),
    }
