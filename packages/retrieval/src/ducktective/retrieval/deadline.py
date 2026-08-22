"""Предел времени на запрос к индексу.

Поиск обещает ответ за доли секунды, а не «когда-нибудь»: на нём стоит
прогон ревью, и запрос, ушедший в минуты, останавливает всё дело целиком.
Ограничение ставится базой, а не отменой на стороне клиента: брошенный
запрос без него продолжает считаться и держать соединение.
"""

from collections.abc import (
    Awaitable,
    Callable,
)

from asyncpg.exceptions import (  # type: ignore[import-untyped]
    QueryCanceledError,
)
from sqlalchemy import (
    text,
)
from sqlalchemy.exc import (
    DBAPIError,
)
from sqlalchemy.ext.asyncio import (
    AsyncSession,
)

from ducktective.core.exceptions import (
    SearchTimedOutError,
)


DEFAULT_SEARCH_TIMEOUT_MS = 5000
"""Сколько отведено одному запросу поиска.

Здоровый запрос отвечает за десятки миллисекунд — на живом индексе закрытой базы
слова занимали 7–9 мс, векторы 41–44. Пять секунд — это не «сколько нужно»,
а «после чего происходящее точно не норма».
"""


async def within_deadline[T](
    session: AsyncSession,
    work: Callable[[], Awaitable[T]],
    *,
    timeout_ms: int = DEFAULT_SEARCH_TIMEOUT_MS,
) -> T:
    """Выполняет запрос под ограничением времени.

    `SET LOCAL` живёт до конца транзакции, поэтому ограничение не протекает
    в чужие сессии и снимается само.
    """
    await session.execute(text(f"SET LOCAL statement_timeout = {int(timeout_ms)}"))

    try:
        return await work()
    except DBAPIError as error:
        if isinstance(error.orig, QueryCanceledError) or isinstance(
            error.orig.__cause__ if error.orig else None, QueryCanceledError
        ):
            raise SearchTimedOutError(f"Поиск по индексу не уложился в {timeout_ms} мс") from error
        raise
