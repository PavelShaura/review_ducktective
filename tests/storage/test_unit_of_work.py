from dataclasses import (
    dataclass,
)
from uuid import (
    uuid4,
)

import pytest

from ducktective.core.events import (
    DomainEvent,
)
from ducktective.core.types import (
    TenantId,
)
from ducktective.storage.unit_of_work import (
    SqlAlchemyUnitOfWork,
)


@dataclass(frozen=True, kw_only=True)
class SomethingHappened(DomainEvent):
    payload: str


class FakeSession:
    def __init__(self) -> None:
        self.commit_calls = 0
        self.rollback_calls = 0
        self.is_closed = False
        self.bound_tenants: list[str] = []

    async def execute(self, statement: object, parameters: dict[str, str]) -> None:
        """Единственный запрос, который единица работы шлёт сама, — имя тенанта."""
        self.bound_tenants.append(parameters["value"])

    async def commit(self) -> None:
        self.commit_calls += 1

    async def rollback(self) -> None:
        self.rollback_calls += 1

    async def close(self) -> None:
        self.is_closed = True


class FakeSessionFactory:
    def __init__(self) -> None:
        self.created_sessions: list[FakeSession] = []

    def __call__(self) -> FakeSession:
        session = FakeSession()
        self.created_sessions.append(session)
        return session


def build_unit_of_work() -> tuple[SqlAlchemyUnitOfWork, FakeSessionFactory]:
    factory = FakeSessionFactory()
    return SqlAlchemyUnitOfWork(factory), factory  # type: ignore[arg-type]


async def test_session_is_closed_on_exit() -> None:
    unit_of_work, factory = build_unit_of_work()

    async with unit_of_work:
        pass

    assert factory.created_sessions[0].is_closed


async def test_exit_without_commit_rolls_back() -> None:
    unit_of_work, factory = build_unit_of_work()

    async with unit_of_work:
        pass

    session = factory.created_sessions[0]
    assert session.commit_calls == 0
    assert session.rollback_calls == 1


async def test_usage_outside_context_is_rejected() -> None:
    unit_of_work, _ = build_unit_of_work()

    with pytest.raises(RuntimeError):
        assert unit_of_work.session is not None


async def test_nested_unit_of_work_is_rejected() -> None:
    unit_of_work, _ = build_unit_of_work()

    async with unit_of_work:
        with pytest.raises(RuntimeError):
            await unit_of_work.__aenter__()


async def test_events_are_collected_once() -> None:
    unit_of_work, _ = build_unit_of_work()

    async with unit_of_work:
        unit_of_work.record_events([SomethingHappened(payload="x")])

        assert len(unit_of_work.collect_events()) == 1
        assert unit_of_work.collect_events() == []


async def test_tenant_is_named_to_every_transaction() -> None:
    factory = FakeSessionFactory()
    tenant_id = TenantId(uuid4())
    unit_of_work = SqlAlchemyUnitOfWork(factory, tenant_id=tenant_id)  # type: ignore[arg-type]

    async with unit_of_work:
        await unit_of_work.commit()

    session = factory.created_sessions[0]
    assert session.bound_tenants == [str(tenant_id), str(tenant_id)]


async def test_transaction_without_tenant_names_nothing() -> None:
    """Контур входа открывает единицу работы без тенанта.

    Пустое значение — не «полный доступ», а «ни одной строки»: политики базы
    сравнивают с ним каждую строку с кодом.
    """
    factory = FakeSessionFactory()
    unit_of_work = SqlAlchemyUnitOfWork(factory)  # type: ignore[arg-type]

    async with unit_of_work:
        pass

    assert factory.created_sessions[0].bound_tenants == [""]
