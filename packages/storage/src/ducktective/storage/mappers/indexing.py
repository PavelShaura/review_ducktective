from dataclasses import (
    asdict,
)

from ducktective.core.indexing.entities import (
    CodeChunk,
    CodeSymbol,
    IndexSnapshot,
    IndexStats,
    SourceFile,
    SymbolEdge,
)
from ducktective.core.indexing.search import (
    build_search_text,
)
from ducktective.core.types import (
    CodeChunkId,
    CodeSymbolId,
    CommitSha,
    ContentHash,
    IndexSnapshotId,
    QualifiedName,
    RepositoryId,
    SourceFileId,
    SymbolEdgeId,
)
from ducktective.storage.models.indexing import (
    CodeChunkModel,
    CodeSymbolModel,
    IndexSnapshotModel,
    SourceFileModel,
    SymbolEdgeModel,
)


def snapshot_to_domain(model: IndexSnapshotModel) -> IndexSnapshot:
    return IndexSnapshot(
        id=IndexSnapshotId(model.id),
        repository_id=RepositoryId(model.repository_id),
        commit_sha=CommitSha(model.commit_sha),
        status=model.status,
        stage=model.stage,
        embedding_stopped=model.embedding_stopped,
        created_at=model.created_at,
        parent_snapshot_id=(
            IndexSnapshotId(model.parent_snapshot_id)
            if model.parent_snapshot_id is not None
            else None
        ),
        stats=IndexStats(**model.stats) if model.stats else IndexStats(),
        started_at=model.started_at,
        finished_at=model.finished_at,
        failure_reason=model.failure_reason,
    )


def snapshot_to_model(snapshot: IndexSnapshot) -> IndexSnapshotModel:
    return IndexSnapshotModel(
        id=snapshot.id,
        repository_id=snapshot.repository_id,
        parent_snapshot_id=snapshot.parent_snapshot_id,
        commit_sha=snapshot.commit_sha,
        status=snapshot.status,
        stage=snapshot.stage,
        embedding_stopped=snapshot.embedding_stopped,
        stats=asdict(snapshot.stats),
        failure_reason=snapshot.failure_reason,
        created_at=snapshot.created_at,
        started_at=snapshot.started_at,
        finished_at=snapshot.finished_at,
    )


def apply_snapshot_changes(model: IndexSnapshotModel, snapshot: IndexSnapshot) -> None:
    model.status = snapshot.status
    model.stage = snapshot.stage
    model.embedding_stopped = snapshot.embedding_stopped
    model.stats = asdict(snapshot.stats)
    model.failure_reason = snapshot.failure_reason
    model.started_at = snapshot.started_at
    model.finished_at = snapshot.finished_at


def source_file_to_domain(model: SourceFileModel) -> SourceFile:
    return SourceFile(
        id=SourceFileId(model.id),
        repository_id=RepositoryId(model.repository_id),
        path=model.path,
        language=model.language,
        content_hash=ContentHash(model.content_hash),
        first_seen_snapshot_id=IndexSnapshotId(model.first_seen_snapshot_id),
        last_seen_snapshot_id=IndexSnapshotId(model.last_seen_snapshot_id),
        is_deleted=model.is_deleted,
        symbols=[_symbol_to_domain(symbol) for symbol in model.symbols],
        chunks=[_chunk_to_domain(chunk) for chunk in model.chunks],
    )


def source_file_to_model(source_file: SourceFile) -> SourceFileModel:
    return SourceFileModel(
        id=source_file.id,
        repository_id=source_file.repository_id,
        path=source_file.path,
        language=source_file.language,
        content_hash=source_file.content_hash,
        first_seen_snapshot_id=source_file.first_seen_snapshot_id,
        last_seen_snapshot_id=source_file.last_seen_snapshot_id,
        is_deleted=source_file.is_deleted,
        symbols=[_symbol_to_model(symbol, source_file) for symbol in source_file.symbols],
        chunks=[_chunk_to_model(chunk, source_file) for chunk in source_file.chunks],
    )


def apply_source_file_changes(model: SourceFileModel, source_file: SourceFile) -> None:
    """Переносит разбор файла в модель.

    Символы и чанки заменяются целиком, а не сверяются поштучно: файл
    переразбирается только когда изменился, и после разбора это другие
    объекты с другими границами.
    """
    model.content_hash = source_file.content_hash
    model.language = source_file.language
    model.last_seen_snapshot_id = source_file.last_seen_snapshot_id
    model.is_deleted = source_file.is_deleted

    if _is_same_parse(model, source_file):
        return

    model.symbols = [_symbol_to_model(symbol, source_file) for symbol in source_file.symbols]
    model.chunks = [_chunk_to_model(chunk, source_file) for chunk in source_file.chunks]


def _is_same_parse(model: SourceFileModel, source_file: SourceFile) -> bool:
    return {symbol.id for symbol in model.symbols} == {
        symbol.id for symbol in source_file.symbols
    } and {chunk.id for chunk in model.chunks} == {chunk.id for chunk in source_file.chunks}


def edge_to_model(edge: SymbolEdge) -> SymbolEdgeModel:
    return SymbolEdgeModel(
        id=edge.id,
        repository_id=edge.repository_id,
        source_symbol_id=edge.source_symbol_id,
        target_symbol_id=edge.target_symbol_id,
        target_qualified_name=edge.target_qualified_name,
        kind=edge.kind,
        is_resolved=edge.is_resolved,
        confidence=edge.confidence,
    )


def edge_to_domain(model: SymbolEdgeModel) -> SymbolEdge:
    return SymbolEdge(
        id=SymbolEdgeId(model.id),
        repository_id=RepositoryId(model.repository_id),
        source_symbol_id=CodeSymbolId(model.source_symbol_id),
        target_symbol_id=(
            CodeSymbolId(model.target_symbol_id) if model.target_symbol_id is not None else None
        ),
        target_qualified_name=(
            QualifiedName(model.target_qualified_name)
            if model.target_qualified_name is not None
            else None
        ),
        kind=model.kind,
        confidence=model.confidence,
    )


def _symbol_to_domain(model: CodeSymbolModel) -> CodeSymbol:
    return CodeSymbol(
        id=CodeSymbolId(model.id),
        kind=model.kind,
        name=model.name,
        qualified_name=QualifiedName(model.qualified_name),
        start_line=model.start_line,
        end_line=model.end_line,
        start_byte=model.start_byte,
        end_byte=model.end_byte,
        content_hash=ContentHash(model.content_hash),
        parent_id=CodeSymbolId(model.parent_symbol_id) if model.parent_symbol_id else None,
        signature=model.signature,
        docstring=model.docstring,
    )


def _symbol_to_model(symbol: CodeSymbol, source_file: SourceFile) -> CodeSymbolModel:
    return CodeSymbolModel(
        id=symbol.id,
        repository_id=source_file.repository_id,
        file_id=source_file.id,
        parent_symbol_id=symbol.parent_id,
        kind=symbol.kind,
        name=symbol.name,
        qualified_name=symbol.qualified_name,
        signature=symbol.signature,
        docstring=symbol.docstring,
        start_line=symbol.start_line,
        end_line=symbol.end_line,
        start_byte=symbol.start_byte,
        end_byte=symbol.end_byte,
        content_hash=symbol.content_hash,
        search_text=build_search_text(
            symbol.qualified_name,
            symbol.signature,
            symbol.docstring,
        ),
    )


def _chunk_to_domain(model: CodeChunkModel) -> CodeChunk:
    return CodeChunk(
        id=CodeChunkId(model.id),
        content=model.content,
        content_hash=ContentHash(model.content_hash),
        token_count=model.token_count,
        start_line=model.start_line,
        end_line=model.end_line,
        breadcrumb=model.breadcrumb,
        symbol_id=CodeSymbolId(model.symbol_id) if model.symbol_id else None,
    )


def _chunk_to_model(chunk: CodeChunk, source_file: SourceFile) -> CodeChunkModel:
    return CodeChunkModel(
        id=chunk.id,
        repository_id=source_file.repository_id,
        file_id=source_file.id,
        symbol_id=chunk.symbol_id,
        content=chunk.content,
        content_hash=chunk.content_hash,
        token_count=chunk.token_count,
        start_line=chunk.start_line,
        end_line=chunk.end_line,
        breadcrumb=chunk.breadcrumb,
        search_text=build_search_text(chunk.breadcrumb, chunk.content),
    )
