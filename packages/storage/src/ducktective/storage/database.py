from collections.abc import (
    AsyncIterator,
)
from contextlib import (
    asynccontextmanager,
)

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


def build_engine(
    database_url: str,
    *,
    pool_size: int = 10,
    max_overflow: int = 5,
    echo: bool = False,
) -> AsyncEngine:
    return create_async_engine(
        database_url,
        pool_size=pool_size,
        max_overflow=max_overflow,
        pool_pre_ping=True,
        echo=echo,
    )


def build_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(
        bind=engine,
        expire_on_commit=False,
        autoflush=False,
    )


@asynccontextmanager
async def read_only_session(
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    """Сессия для чтения: транзакция всегда откатывается, ничего не фиксируется."""
    async with session_factory() as session:
        try:
            yield session
        finally:
            await session.rollback()
