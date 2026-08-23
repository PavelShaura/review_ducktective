from sqlalchemy import (
    text,
)
from sqlalchemy.ext.asyncio import (
    AsyncSession,
)

from ducktective.core.types import (
    TenantId,
)


TENANT_SETTING = "app.tenant_id"

_BIND_STATEMENT = text("select set_config(:name, :value, true)")


async def bind_tenant(session: AsyncSession, tenant_id: TenantId | None) -> None:
    """Называет тенанта транзакции, чтобы политики базы знали, чьё показывать.

    Настройка ставится локальной: она живёт до конца транзакции и не
    протекает на следующего, кому достанется это соединение из пула.

    Пустое значение — не ошибка, а осознанный отказ от доступа: политики
    сравнивают с ним каждую строку и не пропускают ни одной. Именно так
    работает контур доступа — вход и приглашения, — которому тенант ещё
    неизвестен по построению.
    """
    await session.execute(
        _BIND_STATEMENT,
        {"name": TENANT_SETTING, "value": str(tenant_id) if tenant_id else ""},
    )
