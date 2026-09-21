from uuid import (
    uuid4,
)

from ducktective.core.indexing.entities import (
    SourceFile,
    SymbolEdge,
)
from ducktective.core.indexing.value_objects import (
    EdgeKind,
)
from ducktective.core.types import (
    ContentHash,
    IndexSnapshotId,
    QualifiedName,
    RepositoryId,
    SymbolEdgeId,
)
from ducktective.indexing.script_parser import (
    ScriptParser,
)
from ducktective.storage.memory.unit_of_work import (
    InMemoryUnitOfWork,
)


FILES = {
    "src/widget.ts": "export const widget = 1;\n",
    "src/foo.test.ts": "export const helper = 1;\n",
    "src/foo.test.tsx": "export const Rendered = () => null;\n",
}


async def test_name_shared_by_two_files_is_left_unresolved() -> None:
    unit_of_work = InMemoryUnitOfWork()
    repository_id = RepositoryId(uuid4())
    snapshot_id = IndexSnapshotId(uuid4())
    parser = ScriptParser()

    async with unit_of_work:
        sources = []
        for path, content in FILES.items():
            parsed = parser.parse(path=path, content=content)
            source_file = SourceFile.create(
                repository_id=repository_id,
                path=path,
                language="typescript",
                content_hash=ContentHash(f"hash-{path}"),
                snapshot_id=snapshot_id,
            )
            source_file.replace_contents(
                content_hash=ContentHash(f"hash-{path}"),
                symbols=parsed.symbols,
                chunks=parsed.chunks,
                snapshot_id=snapshot_id,
            )
            unit_of_work.source_files.add(source_file)
            sources.append(parsed.symbols[0].id)

        edges = [
            SymbolEdge(
                id=SymbolEdgeId(uuid4()),
                repository_id=repository_id,
                source_symbol_id=sources[0],
                kind=EdgeKind.IMPORTS,
                target_qualified_name=QualifiedName(target),
            )
            for target in ("src.widget", "src.foo.test")
        ]
        await unit_of_work.symbol_edges.replace_for_symbols(repository_id, [], edges)
        resolved = await unit_of_work.symbol_edges.resolve_pending(repository_id)
        await unit_of_work.commit()

    assert resolved == 1
    assert [edge.is_resolved for edge in edges] == [True, False]
