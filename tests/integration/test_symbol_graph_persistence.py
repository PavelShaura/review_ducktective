from pathlib import (
    Path,
)
from uuid import (
    uuid4,
)

import pytest
from sqlalchemy import (
    func,
    select,
)
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
    SymbolEdge,
)
from ducktective.core.types import (
    CommitSha,
    ContentHash,
    RepositoryId,
    SymbolEdgeId,
    TenantId,
)
from ducktective.indexing.script_parser import (
    ScriptParser,
)
from ducktective.storage.models.indexing import (
    CodeSymbolModel,
    SymbolEdgeModel,
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


FILES = {
    "src/widget.ts": "export const widget = 1;\n",
    "src/foo.test.ts": "export const helper = 1;\n",
    "src/foo.test.tsx": "export const Rendered = () => null;\n",
    "src/app.ts": 'import { widget } from "src/widget";\nimport { helper } from "src/foo.test";\n',
}


async def seed(
    session_factory: async_sessionmaker[AsyncSession],
) -> tuple[TenantId, RepositoryId]:
    tenant_id = TenantId(uuid4())
    async with session_factory() as session:
        session.add(TenantModel(id=tenant_id, slug=f"t-{tenant_id.hex[:8]}", name="Тест"))
        await session.commit()

    unit_of_work = SqlAlchemyUnitOfWork(session_factory, tenant_id=tenant_id)
    parser = ScriptParser()

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

        edges: list[SymbolEdge] = []
        for path, content in FILES.items():
            parsed = parser.parse(path=path, content=content)
            source_file = SourceFile.create(
                repository_id=repository.id,
                path=path,
                language="typescript",
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
            edges.extend(
                SymbolEdge(
                    id=SymbolEdgeId(uuid4()),
                    repository_id=repository.id,
                    source_symbol_id=reference.source_symbol_id,
                    kind=reference.kind,
                    target_qualified_name=reference.target_name,
                )
                for reference in parsed.references
            )

        await unit_of_work.commit()

    async with unit_of_work:
        await unit_of_work.symbol_edges.replace_for_symbols(repository.id, [], edges)
        await unit_of_work.commit()

    return tenant_id, repository.id


async def test_two_files_with_one_module_path_are_both_stored(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """`foo.test.ts` рядом с `foo.test.tsx` — обычное соседство, и индекс его выдерживает."""
    tenant_id, repository_id = await seed(session_factory)

    async with session_factory() as session:
        await bind_tenant(session, tenant_id)
        stored = await session.scalar(
            select(func.count())
            .select_from(CodeSymbolModel)
            .where(
                CodeSymbolModel.repository_id == repository_id,
                CodeSymbolModel.qualified_name == "src.foo.test",
            )
        )

    assert stored == 2


async def test_import_resolves_only_to_a_name_that_lives_in_one_file(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    tenant_id, repository_id = await seed(session_factory)

    unit_of_work = SqlAlchemyUnitOfWork(session_factory, tenant_id=tenant_id)
    async with unit_of_work:
        resolved = await unit_of_work.symbol_edges.resolve_pending(repository_id)
        await unit_of_work.commit()

    async with session_factory() as session:
        await bind_tenant(session, tenant_id)
        rows = await session.execute(
            select(SymbolEdgeModel.target_qualified_name, SymbolEdgeModel.is_resolved).where(
                SymbolEdgeModel.repository_id == repository_id
            )
        )
        outcome = dict(rows.tuples().all())

    assert resolved == 1
    assert outcome == {"src.widget": True, "src.foo.test": False}
