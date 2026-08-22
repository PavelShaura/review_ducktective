from uuid import (
    uuid4,
)

import pytest

from ducktective.core.diff.value_objects import (
    LineRange,
)
from ducktective.core.exceptions import (
    InvariantViolationError,
)
from ducktective.core.indexing.entities import (
    CodeChunk,
    CodeSymbol,
    IndexSnapshot,
    IndexStats,
    SourceFile,
    SymbolEdge,
)
from ducktective.core.indexing.events import (
    IndexSnapshotCreated,
    IndexSnapshotStatusChanged,
    SourceFileIndexed,
)
from ducktective.core.indexing.value_objects import (
    EdgeKind,
    SnapshotStage,
    SnapshotStatus,
    SymbolKind,
)
from ducktective.core.types import (
    CodeChunkId,
    CodeSymbolId,
    CommitSha,
    ContentHash,
    QualifiedName,
    RepositoryId,
    SymbolEdgeId,
)


def build_snapshot() -> IndexSnapshot:
    return IndexSnapshot.create(
        repository_id=RepositoryId(uuid4()),
        commit_sha=CommitSha("a" * 40),
    )


def build_symbol(
    name: str,
    start_line: int,
    end_line: int,
    kind: SymbolKind = SymbolKind.METHOD,
) -> CodeSymbol:
    return CodeSymbol(
        id=CodeSymbolId(uuid4()),
        kind=kind,
        name=name.rsplit(".", maxsplit=1)[-1],
        qualified_name=QualifiedName(name),
        start_line=start_line,
        end_line=end_line,
        start_byte=0,
        end_byte=100,
        content_hash=ContentHash("b" * 64),
    )


def build_file(snapshot: IndexSnapshot) -> SourceFile:
    return SourceFile.create(
        repository_id=snapshot.repository_id,
        path="app/report.py",
        language="python",
        content_hash=ContentHash("c" * 64),
        snapshot_id=snapshot.id,
    )


def test_created_snapshot_announces_itself() -> None:
    snapshot = build_snapshot()

    events = snapshot.pull_events()

    assert snapshot.status is SnapshotStatus.PENDING
    assert snapshot.is_incremental is False
    assert any(isinstance(event, IndexSnapshotCreated) for event in events)


def test_snapshot_reaches_ready_with_stats() -> None:
    snapshot = build_snapshot()
    snapshot.pull_events()

    snapshot.mark_running()
    snapshot.mark_ready(IndexStats(files_total=12, files_parsed=3, symbols=40, chunks=57))

    assert snapshot.status is SnapshotStatus.READY
    assert snapshot.stats.files_parsed == 3
    assert snapshot.finished_at is not None
    assert len(snapshot.pull_events()) == 2


def test_unfinished_vectors_are_reported_without_failing_the_snapshot() -> None:
    """Символы и граф записаны — снапшот готов, и отказ эмбеддера этого не меняет.

    Молчать при этом нельзя: остановившийся досчёт неотличим от идущего,
    и доля посчитанных векторов замирает, продолжая обещать поиск по смыслу.
    """
    snapshot = build_snapshot()
    snapshot.mark_running()
    snapshot.mark_ready(IndexStats(files_total=12, chunks=57))
    snapshot.enter_stage(SnapshotStage.EMBEDDING)

    snapshot.record_embedding_failure("модель эмбеддингов не ответила")

    assert snapshot.status is SnapshotStatus.READY
    assert snapshot.failure_reason == "модель эмбеддингов не ответила"


def test_finished_snapshot_does_not_change_status() -> None:
    snapshot = build_snapshot()
    snapshot.mark_running()
    snapshot.mark_failed("git недоступен")

    with pytest.raises(InvariantViolationError):
        snapshot.mark_ready(IndexStats())


def test_status_change_is_announced() -> None:
    snapshot = build_snapshot()
    snapshot.pull_events()

    snapshot.mark_running()

    events = snapshot.pull_events()
    assert isinstance(events[0], IndexSnapshotStatusChanged)
    assert events[0].current_status is SnapshotStatus.RUNNING


def test_snapshot_with_parent_is_incremental() -> None:
    parent = build_snapshot()
    child = IndexSnapshot.create(
        repository_id=parent.repository_id,
        commit_sha=CommitSha("d" * 40),
        parent_snapshot_id=parent.id,
    )

    assert child.is_incremental is True


def test_reindexed_file_replaces_previous_parse() -> None:
    snapshot = build_snapshot()
    source_file = build_file(snapshot)
    source_file.replace_contents(
        content_hash=ContentHash("1" * 64),
        symbols=[build_symbol("app.report.Builder.build", 10, 20)],
        chunks=[],
        snapshot_id=snapshot.id,
    )
    source_file.pull_events()

    source_file.replace_contents(
        content_hash=ContentHash("2" * 64),
        symbols=[build_symbol("app.report.Builder.render", 10, 25)],
        chunks=[
            CodeChunk(
                id=CodeChunkId(uuid4()),
                content="def render(self): ...",
                content_hash=ContentHash("3" * 64),
                token_count=8,
                start_line=10,
                end_line=25,
                breadcrumb="app.report > Builder > render",
            )
        ],
        snapshot_id=snapshot.id,
    )

    assert [symbol.name for symbol in source_file.symbols] == ["render"]
    assert len(source_file.chunks) == 1
    assert source_file.content_hash == ContentHash("2" * 64)


def test_indexed_file_announces_its_contents() -> None:
    snapshot = build_snapshot()
    source_file = build_file(snapshot)

    source_file.replace_contents(
        content_hash=ContentHash("1" * 64),
        symbols=[build_symbol("app.report.Builder", 1, 40, SymbolKind.CLASS)],
        chunks=[],
        snapshot_id=snapshot.id,
    )

    events = source_file.pull_events()
    assert isinstance(events[0], SourceFileIndexed)
    assert events[0].symbols == 1


def test_hunk_lines_resolve_to_symbols() -> None:
    snapshot = build_snapshot()
    source_file = build_file(snapshot)
    source_file.replace_contents(
        content_hash=ContentHash("1" * 64),
        symbols=[
            build_symbol("app.report.Builder", 1, 40, SymbolKind.CLASS),
            build_symbol("app.report.Builder.build", 10, 20),
            build_symbol("app.report.Builder.render", 22, 38),
        ],
        chunks=[],
        snapshot_id=snapshot.id,
    )

    covering = source_file.symbols_covering(LineRange(start=12, end=14))

    assert [symbol.qualified_name for symbol in covering] == [
        "app.report.Builder",
        "app.report.Builder.build",
    ]


def test_deleted_file_keeps_its_parse() -> None:
    snapshot = build_snapshot()
    source_file = build_file(snapshot)
    source_file.replace_contents(
        content_hash=ContentHash("1" * 64),
        symbols=[build_symbol("app.report.Builder.build", 10, 20)],
        chunks=[],
        snapshot_id=snapshot.id,
    )

    source_file.mark_deleted(snapshot.id)

    assert source_file.is_deleted is True
    assert len(source_file.symbols) == 1


def test_unresolved_edge_keeps_target_name() -> None:
    edge = SymbolEdge(
        id=SymbolEdgeId(uuid4()),
        repository_id=RepositoryId(uuid4()),
        source_symbol_id=CodeSymbolId(uuid4()),
        kind=EdgeKind.CALLS,
        target_qualified_name=QualifiedName("app.util.render"),
    )

    assert edge.is_resolved is False
    assert edge.target_qualified_name == "app.util.render"


def test_edge_without_any_target_is_rejected() -> None:
    with pytest.raises(InvariantViolationError):
        SymbolEdge(
            id=SymbolEdgeId(uuid4()),
            repository_id=RepositoryId(uuid4()),
            source_symbol_id=CodeSymbolId(uuid4()),
            kind=EdgeKind.CALLS,
        )
