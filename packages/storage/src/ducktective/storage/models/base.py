from datetime import (
    datetime,
)
from uuid import (
    UUID,
)

from sqlalchemy import (
    DateTime,
    Dialect,
    MetaData,
    Uuid,
)
from sqlalchemy.orm import (
    DeclarativeBase,
)
from sqlalchemy.types import (
    TypeDecorator,
)


NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class StdlibUuid(TypeDecorator[UUID]):
    """Идентификатор из базы приводится к `uuid.UUID` домена.

    asyncpg отдаёт `pgproto.UUID` — наследника `uuid.UUID`, поэтому подмена
    не видна ни в сравнении, ни в проверке типа, и доменные объекты носят
    тип драйвера, не подавая виду. Видно её там, где тип называют по имени:
    сохранённое состояние графа восстанавливается по имени класса, и
    незнакомый идентификатор возвращается строкой вместо UUID — прогон
    рассыпается ровно в момент продолжения.

    Приведение стоит здесь, а не в мапперах: граница драйвера одна,
    а мапперов два десятка.
    """

    impl = Uuid
    cache_ok = True

    def process_result_value(self, value: UUID | None, dialect: Dialect) -> UUID | None:
        if value is None or type(value) is UUID:
            return value
        return UUID(bytes=value.bytes)


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
        UUID: StdlibUuid(),
    }
