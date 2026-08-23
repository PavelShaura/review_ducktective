from pathlib import (
    Path,
)
from uuid import (
    uuid4,
)

import pytest
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
)

from ducktective.core.code_repository.entities import (
    CodeRepository,
)
from ducktective.core.code_repository.value_objects import (
    VcsProvider,
)
from ducktective.core.indexing.entities import (
    IndexSnapshot,
    IndexStats,
    SourceFile,
)
from ducktective.core.types import (
    CommitSha,
    ContentHash,
    RepositoryId,
    TenantId,
)
from ducktective.indexing.python_parser import (
    PythonParser,
)
from ducktective.retrieval.lexical import (
    PostgresLexicalSearch,
)
from ducktective.storage.models.tenancy import (
    TenantModel,
)
from ducktective.storage.tenant_scope import (
    bind_tenant,
)
from ducktective.storage.unit_of_work import (
    SqlAlchemyUnitOfWork,
)


pytestmark = pytest.mark.integration


MODULE = '''"""Отчёты по успеваемости."""

from decimal import Decimal


class ReportBuilder:
    """Собирает отчёт из оценок."""

    def build_total(self, grades):
        """Считает итоговый балл."""
        return Decimal(sum(grades))
'''

OTHER_MODULE = """
class PaymentGateway:
    def charge(self, amount):
        return amount
"""


async def seed(
    session_factory: async_sessionmaker[AsyncSession],
) -> tuple[TenantId, RepositoryId]:
    tenant_id = TenantId(uuid4())
    async with session_factory() as session:
        session.add(TenantModel(id=tenant_id, slug=f"t-{tenant_id.hex[:8]}", name="Тест"))
        await session.commit()

    unit_of_work = SqlAlchemyUnitOfWork(session_factory, tenant_id=tenant_id)
    parser = PythonParser()

    async with unit_of_work:
        repository = CodeRepository.register(
            tenant_id=tenant_id,
            name="sandbox",
            vcs_provider=VcsProvider.LOCAL,
            local_path=Path("/repos/sandbox"),
        )
        unit_of_work.code_repositories.add(repository)

        snapshot = IndexSnapshot.create(
            repository_id=repository.id,
            commit_sha=CommitSha("a" * 40),
        )
        snapshot.mark_running()
        snapshot.mark_ready(IndexStats())
        unit_of_work.index_snapshots.add(snapshot)

        for path, content in (("app/report.py", MODULE), ("app/billing.py", OTHER_MODULE)):
            parsed = parser.parse(path=path, content=content)
            source_file = SourceFile.create(
                repository_id=repository.id,
                path=path,
                language="python",
                content_hash=ContentHash(f"hash-{path}"),
                snapshot_id=snapshot.id,
            )
            source_file.replace_contents(
                content_hash=ContentHash(f"hash-{path}"),
                symbols=parsed.symbols,
                chunks=parsed.chunks,
                snapshot_id=snapshot.id,
            )
            unit_of_work.source_files.add(source_file)

        await unit_of_work.commit()
        return tenant_id, repository.id


async def test_symbol_is_found_by_part_of_its_name(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """`build_total` находится по слову «total» — ради этого имена и разбиваются."""
    tenant_id, repository_id = await seed(session_factory)

    async with session_factory() as session:
        await bind_tenant(session, tenant_id)
        hits = await PostgresLexicalSearch(session).search_symbols(repository_id, "total")

    assert any(hit.qualified_name.endswith("build_total") for hit in hits)


async def test_camel_case_class_is_found_by_one_word(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    tenant_id, repository_id = await seed(session_factory)

    async with session_factory() as session:
        await bind_tenant(session, tenant_id)
        hits = await PostgresLexicalSearch(session).search_symbols(repository_id, "Report")

    assert any(hit.qualified_name.endswith("ReportBuilder") for hit in hits)


async def test_docstring_words_reach_the_index(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    tenant_id, repository_id = await seed(session_factory)

    async with session_factory() as session:
        await bind_tenant(session, tenant_id)
        hits = await PostgresLexicalSearch(session).search_chunks(repository_id, "успеваемости")

    assert any("report" in hit.path for hit in hits)


async def test_results_carry_their_location(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    tenant_id, repository_id = await seed(session_factory)

    async with session_factory() as session:
        await bind_tenant(session, tenant_id)
        hits = await PostgresLexicalSearch(session).search_chunks(repository_id, "Decimal")

    assert hits
    assert all(hit.start_line <= hit.end_line for hit in hits)
    assert all(hit.breadcrumb for hit in hits)


async def test_unrelated_query_returns_nothing(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    tenant_id, repository_id = await seed(session_factory)

    async with session_factory() as session:
        await bind_tenant(session, tenant_id)
        hits = await PostgresLexicalSearch(session).search_symbols(repository_id, "kubernetes")

    assert hits == []


async def test_ranking_puts_the_relevant_file_first(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    tenant_id, repository_id = await seed(session_factory)

    async with session_factory() as session:
        await bind_tenant(session, tenant_id)
        hits = await PostgresLexicalSearch(session).search_chunks(repository_id, "charge amount")

    assert hits
    assert "billing" in hits[0].path
