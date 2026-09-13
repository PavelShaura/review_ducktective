from pathlib import (
    Path,
)
from uuid import (
    uuid4,
)

import pytest

from ducktective.application.exceptions import (
    PermissionDeniedError,
)
from ducktective.application.indexing import build_index as build_index_module
from ducktective.application.indexing.build_index import (
    BuildIndex,
    BuildIndexCommand,
    IndexingCancelledError,
    IndexOutcome,
)
from ducktective.application.indexing.embedders import (
    EmbedderCatalogue,
    EmbedderChoice,
)
from ducktective.application.indexing.enqueue import (
    EnqueueIndexing,
)
from ducktective.application.indexing.ensure_for_revision import (
    EnsureIndexForRevision,
)
from ducktective.application.indexing.read_state import (
    GetIndexState,
)
from ducktective.core.code_repository.entities import (
    CodeRepository,
)
from ducktective.core.code_repository.value_objects import VcsProvider as VcsProviderKind
from ducktective.core.indexing.value_objects import (
    SnapshotStage,
    SnapshotStatus,
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
from tests.fakes import (
    FakeEventPublisher,
    FakeUnitOfWork,
    FakeVcsProvider,
)


def catalogue(*names: str) -> EmbedderCatalogue:
    return EmbedderCatalogue(
        [
            EmbedderChoice(key=name, title=name, vector_set=name)
            for name in names or ("fake-embedder",)
        ]
    )


MODULE = "class Builder:\n    def build(self):\n        return 1\n"
CHANGED_MODULE = "class Builder:\n    def build(self):\n        return 2\n\n    def render(self):\n        return 3\n"


def prepare(unit_of_work: FakeUnitOfWork) -> tuple[TenantId, RepositoryId]:
    tenant_id = TenantId(uuid4())
    repository = CodeRepository.register(
        tenant_id=tenant_id,
        name="sandbox",
        vcs_provider=VcsProviderKind.LOCAL,
        local_path=Path("/repos/sandbox"),
    )
    unit_of_work.code_repositories.add(repository)
    return tenant_id, repository.id


async def build(
    unit_of_work: FakeUnitOfWork,
    vcs_provider: FakeVcsProvider,
    tenant_id: TenantId,
    repository_id: RepositoryId,
) -> IndexOutcome:
    return await BuildIndex(
        unit_of_work,
        FakeEventPublisher(),
        vcs_provider,
        PythonParser(),
    ).execute(BuildIndexCommand(tenant_id=tenant_id, repository_id=repository_id))


async def test_first_run_parses_every_supported_file() -> None:
    unit_of_work = FakeUnitOfWork()
    tenant_id, repository_id = prepare(unit_of_work)
    vcs_provider = FakeVcsProvider(
        tree={"app/report.py": ContentHash("hash-1")},
        file_contents={"app/report.py": MODULE},
    )

    outcome = await build(unit_of_work, vcs_provider, tenant_id, repository_id)

    assert outcome.snapshot.status is SnapshotStatus.READY
    assert outcome.is_incremental is False
    assert outcome.stats.files_parsed == 1
    assert outcome.stats.files_reused == 0
    assert outcome.stats.symbols > 0


async def test_unchanged_files_are_not_parsed_again() -> None:
    """Инкрементальность: совпал хеш — файл не читается и не разбирается."""
    unit_of_work = FakeUnitOfWork()
    tenant_id, repository_id = prepare(unit_of_work)
    vcs_provider = FakeVcsProvider(
        tree={"app/report.py": ContentHash("hash-1")},
        file_contents={"app/report.py": MODULE},
    )
    await build(unit_of_work, vcs_provider, tenant_id, repository_id)

    outcome = await build(unit_of_work, vcs_provider, tenant_id, repository_id)

    assert outcome.is_incremental is True
    assert outcome.stats.files_parsed == 0
    assert outcome.stats.files_reused == 1


async def test_changed_file_replaces_its_previous_parse() -> None:
    unit_of_work = FakeUnitOfWork()
    tenant_id, repository_id = prepare(unit_of_work)
    vcs_provider = FakeVcsProvider(
        tree={"app/report.py": ContentHash("hash-1")},
        file_contents={"app/report.py": MODULE},
    )
    await build(unit_of_work, vcs_provider, tenant_id, repository_id)

    vcs_provider.tree = {"app/report.py": ContentHash("hash-2")}
    vcs_provider.file_contents = {"app/report.py": CHANGED_MODULE}
    outcome = await build(unit_of_work, vcs_provider, tenant_id, repository_id)

    source_file = await unit_of_work.source_files.find_by_path(repository_id, "app/report.py")
    assert outcome.stats.files_parsed == 1
    assert source_file is not None
    assert source_file.content_hash == "hash-2"
    assert any(symbol.name == "render" for symbol in source_file.symbols)


async def test_vanished_file_is_marked_deleted_but_kept() -> None:
    """Символы исчезнувшего файла остаются: на них ссылаются прошлые находки."""
    unit_of_work = FakeUnitOfWork()
    tenant_id, repository_id = prepare(unit_of_work)
    vcs_provider = FakeVcsProvider(
        tree={"app/report.py": ContentHash("hash-1")},
        file_contents={"app/report.py": MODULE},
    )
    await build(unit_of_work, vcs_provider, tenant_id, repository_id)

    vcs_provider.tree = {}
    outcome = await build(unit_of_work, vcs_provider, tenant_id, repository_id)

    source_file = await unit_of_work.source_files.find_by_path(repository_id, "app/report.py")
    assert outcome.stats.files_deleted == 1
    assert source_file is not None
    assert source_file.is_deleted is True
    assert source_file.symbols


async def test_unsupported_languages_are_skipped() -> None:
    unit_of_work = FakeUnitOfWork()
    tenant_id, repository_id = prepare(unit_of_work)
    vcs_provider = FakeVcsProvider(
        tree={
            "app/report.py": ContentHash("hash-1"),
            "web/app.ts": ContentHash("hash-2"),
            "README.md": ContentHash("hash-3"),
        },
        file_contents={"app/report.py": MODULE},
    )

    outcome = await build(unit_of_work, vcs_provider, tenant_id, repository_id)

    assert outcome.stats.files_total == 1
    assert outcome.stats.files_parsed == 1


async def test_unreadable_file_is_reported_without_failing_the_run() -> None:
    unit_of_work = FakeUnitOfWork()
    tenant_id, repository_id = prepare(unit_of_work)
    vcs_provider = FakeVcsProvider(
        tree={"app/report.py": ContentHash("hash-1")},
        file_contents={},
    )

    outcome = await build(unit_of_work, vcs_provider, tenant_id, repository_id)

    assert outcome.snapshot.status is SnapshotStatus.READY
    assert outcome.unreadable == ("app/report.py",)
    assert outcome.stats.files_parsed == 0


async def test_snapshot_chain_points_at_the_previous_one() -> None:
    unit_of_work = FakeUnitOfWork()
    tenant_id, repository_id = prepare(unit_of_work)
    vcs_provider = FakeVcsProvider(
        tree={"app/report.py": ContentHash("hash-1")},
        file_contents={"app/report.py": MODULE},
    )
    first = await build(unit_of_work, vcs_provider, tenant_id, repository_id)

    second = await build(unit_of_work, vcs_provider, tenant_id, repository_id)

    assert second.snapshot.parent_snapshot_id == first.snapshot.id


async def test_foreign_tenant_is_rejected() -> None:
    unit_of_work = FakeUnitOfWork()
    _, repository_id = prepare(unit_of_work)
    vcs_provider = FakeVcsProvider(tree={}, file_contents={})

    with pytest.raises(PermissionDeniedError):
        await build(unit_of_work, vcs_provider, TenantId(uuid4()), repository_id)


async def test_files_from_failed_snapshot_are_parsed_again() -> None:
    """Прерванная индексация не должна оставлять индекс битым навсегда."""
    unit_of_work = FakeUnitOfWork()
    tenant_id, repository_id = prepare(unit_of_work)
    vcs_provider = FakeVcsProvider(
        tree={"app/report.py": ContentHash("hash-1")},
        file_contents={"app/report.py": MODULE},
    )
    await build(unit_of_work, vcs_provider, tenant_id, repository_id)

    snapshot = await unit_of_work.index_snapshots.find_latest(repository_id)
    assert snapshot is not None
    snapshot.status = SnapshotStatus.FAILED

    outcome = await build(unit_of_work, vcs_provider, tenant_id, repository_id)

    assert outcome.stats.files_parsed == 1
    assert outcome.stats.files_reused == 0


async def test_files_from_ready_snapshot_are_reused() -> None:
    unit_of_work = FakeUnitOfWork()
    tenant_id, repository_id = prepare(unit_of_work)
    vcs_provider = FakeVcsProvider(
        tree={"app/report.py": ContentHash("hash-1")},
        file_contents={"app/report.py": MODULE},
    )
    await build(unit_of_work, vcs_provider, tenant_id, repository_id)

    outcome = await build(unit_of_work, vcs_provider, tenant_id, repository_id)

    assert outcome.stats.files_parsed == 0
    assert outcome.stats.files_reused == 1


async def test_cancelled_run_stops_and_writes_nothing() -> None:
    """Отмена откатывает работу: до конца всё живёт в памяти."""
    unit_of_work = FakeUnitOfWork()
    tenant_id, repository_id = prepare(unit_of_work)
    vcs_provider = FakeVcsProvider(
        tree={f"app/module_{number}.py": ContentHash(f"hash-{number}") for number in range(60)},
        file_contents={f"app/module_{number}.py": MODULE for number in range(60)},
    )

    class CancellingSnapshots:
        """Отменяет прогон, как только он спросит о своём состоянии."""

        def __init__(self, inner: object) -> None:
            self._inner = inner
            self.asked = 0

        def __getattr__(self, name: str) -> object:
            return getattr(self._inner, name)

        async def get(self, snapshot_id: object) -> object:
            snapshot = await self._inner.get(snapshot_id)  # type: ignore[attr-defined]
            self.asked += 1
            if self.asked > 1:
                snapshot.status = SnapshotStatus.CANCELLED
            return snapshot

    unit_of_work.index_snapshots = CancellingSnapshots(unit_of_work.index_snapshots)  # type: ignore[assignment]

    with pytest.raises(IndexingCancelledError):
        await build(unit_of_work, vcs_provider, tenant_id, repository_id)

    assert await unit_of_work.source_files.list_paths(repository_id) == {}


async def test_stage_moves_from_parsing_to_storing() -> None:
    """Этап нужен интерфейсу: шкала разбора кончается задолго до конца работы."""
    unit_of_work = FakeUnitOfWork()
    tenant_id, repository_id = prepare(unit_of_work)
    vcs_provider = FakeVcsProvider(
        tree={"app/report.py": ContentHash("hash-1")},
        file_contents={"app/report.py": MODULE},
    )

    outcome = await build(unit_of_work, vcs_provider, tenant_id, repository_id)

    assert outcome.snapshot.stage is SnapshotStage.LINKING


async def test_storing_counts_written_files(monkeypatch: pytest.MonkeyPatch) -> None:
    """Одной транзакцией на тысячи файлов шкала застывала и выглядела поломкой.

    Знаменатель у записи свой: пишутся только изменившиеся файлы, а не всё
    дерево, поэтому счётчик записи считается отдельно от разбора.
    """
    monkeypatch.setattr(build_index_module, "STORE_BATCH_SIZE", 2)

    unit_of_work = FakeUnitOfWork()
    tenant_id, repository_id = prepare(unit_of_work)
    paths = [f"app/module_{number}.py" for number in range(5)]
    vcs_provider = FakeVcsProvider(
        tree={path: ContentHash(f"hash-{path}") for path in paths},
        file_contents=dict.fromkeys(paths, MODULE),
    )

    outcome = await build(unit_of_work, vcs_provider, tenant_id, repository_id)

    assert outcome.stats.files_parsed == 5
    assert outcome.stats.files_stored == 5


async def test_context_stays_available_while_the_index_is_rebuilt() -> None:
    """Идущая пересборка не отнимает окружение у ревью.

    Контекст берётся из последнего завершённого снапшота, поэтому запуск
    расследования во время сборки не обесценивает его — но только если
    завершённый снапшот вообще есть.
    """
    unit_of_work = FakeUnitOfWork()
    tenant_id, repository_id = prepare(unit_of_work)
    vcs_provider = FakeVcsProvider(
        tree={"app/report.py": ContentHash("hash-1")},
        file_contents={"app/report.py": MODULE},
    )
    await build(unit_of_work, vcs_provider, tenant_id, repository_id)

    await EnqueueIndexing(unit_of_work, FakeEventPublisher(), vcs_provider).execute(
        tenant_id,
        repository_id,
        "HEAD",
    )

    state = await GetIndexState(unit_of_work, embedders=catalogue()).execute(
        tenant_id, repository_id
    )

    assert state.status is SnapshotStatus.PENDING
    assert state.is_ready is False
    assert state.context_ready is True


async def test_first_build_leaves_review_without_context() -> None:
    unit_of_work = FakeUnitOfWork()
    tenant_id, repository_id = prepare(unit_of_work)

    await EnqueueIndexing(unit_of_work, FakeEventPublisher(), FakeVcsProvider()).execute(
        tenant_id,
        repository_id,
        "HEAD",
    )

    state = await GetIndexState(unit_of_work, embedders=catalogue()).execute(
        tenant_id, repository_id
    )

    assert state.context_ready is False


async def test_vector_coverage_is_reported_separately_from_readiness() -> None:
    """Снапшот готов до подсчёта векторов, и это разные состояния.

    Иначе индекс выглядит собранным, хотя поиск по смыслу ещё не работает,
    и вывод о качестве ревью делается по неполному индексу.
    """
    unit_of_work = FakeUnitOfWork()
    tenant_id, repository_id = prepare(unit_of_work)
    vcs_provider = FakeVcsProvider(
        tree={"app/report.py": ContentHash("hash-1")},
        file_contents={"app/report.py": MODULE},
    )
    await build(unit_of_work, vcs_provider, tenant_id, repository_id)

    state = await GetIndexState(unit_of_work, embedders=catalogue()).execute(
        tenant_id, repository_id
    )

    assert state.is_ready is True
    assert state.vectors.chunks > 0
    assert state.vectors.embedded == 0
    assert state.vectors.is_complete is False


async def test_vectors_of_another_model_do_not_count_as_coverage() -> None:
    """Поиск ищет по векторам активной модели; чужие векторы ему не помогают."""
    unit_of_work = FakeUnitOfWork()
    tenant_id, repository_id = prepare(unit_of_work)
    vcs_provider = FakeVcsProvider(
        tree={"app/report.py": ContentHash("hash-1")},
        file_contents={"app/report.py": MODULE},
    )
    await build(unit_of_work, vcs_provider, tenant_id, repository_id)
    old_model = await unit_of_work.embeddings.register_model("old-embedder", 3)
    pending = await unit_of_work.embeddings.missing_chunks(repository_id, old_model)
    await unit_of_work.embeddings.store(
        old_model, [(chunk_id, [0.0, 0.0, 1.0]) for chunk_id, _, _ in pending]
    )

    old = await GetIndexState(unit_of_work, embedders=catalogue("old-embedder")).execute(
        tenant_id, repository_id
    )
    new = await GetIndexState(unit_of_work, embedders=catalogue()).execute(tenant_id, repository_id)

    assert old.vectors.embedded == old.vectors.chunks
    assert new.vectors.embedded == 0


async def test_totals_come_from_the_index_not_from_the_last_build() -> None:
    """Инкрементальная сборка без изменений разбирает ноль файлов — это не размер индекса."""
    unit_of_work = FakeUnitOfWork()
    tenant_id, repository_id = prepare(unit_of_work)
    vcs_provider = FakeVcsProvider(
        tree={"app/report.py": ContentHash("hash-1")},
        file_contents={"app/report.py": MODULE},
    )
    await build(unit_of_work, vcs_provider, tenant_id, repository_id)
    await build(unit_of_work, vcs_provider, tenant_id, repository_id)

    state = await GetIndexState(unit_of_work, embedders=catalogue()).execute(
        tenant_id, repository_id
    )

    assert state.stats is not None
    assert state.stats.files_parsed == 0
    assert state.totals.files == 1
    assert state.totals.symbols > 0
    assert state.totals.chunks > 0


async def test_embedding_is_reported_only_while_the_snapshot_is_on_that_stage() -> None:
    unit_of_work = FakeUnitOfWork()
    tenant_id, repository_id = prepare(unit_of_work)
    vcs_provider = FakeVcsProvider(
        tree={"app/report.py": ContentHash("hash-1")},
        file_contents={"app/report.py": MODULE},
    )
    await build(unit_of_work, vcs_provider, tenant_id, repository_id)
    read = GetIndexState(unit_of_work, embedders=catalogue())

    before = await read.execute(tenant_id, repository_id)
    assert before.snapshot_id is not None
    async with unit_of_work:
        snapshot = await unit_of_work.index_snapshots.get(before.snapshot_id)
        snapshot.enter_stage(SnapshotStage.EMBEDDING)
        await unit_of_work.commit()
    during = await read.execute(tenant_id, repository_id)
    async with unit_of_work:
        snapshot = await unit_of_work.index_snapshots.get(before.snapshot_id)
        snapshot.finish_embedding()
        await unit_of_work.commit()
    after = await read.execute(tenant_id, repository_id)

    assert before.is_embedding is False
    assert during.is_embedding is True
    assert after.is_embedding is False
    assert after.vectors.embedded < after.vectors.chunks


async def test_chosen_embedder_is_remembered_by_the_repository() -> None:
    """Поиск ищет по набору выбранного сервера, поэтому выбор живёт у репозитория."""
    unit_of_work = FakeUnitOfWork()
    tenant_id, repository_id = prepare(unit_of_work)

    await EnqueueIndexing(unit_of_work, FakeEventPublisher(), FakeVcsProvider()).execute(
        tenant_id,
        repository_id,
        "HEAD",
        embedding_backend="gpu-host",
    )

    async with unit_of_work:
        repository = await unit_of_work.code_repositories.get(repository_id)
    state = await GetIndexState(
        unit_of_work, embedders=catalogue("fake-embedder", "gpu-host")
    ).execute(tenant_id, repository_id)

    assert repository.embedding_backend == "gpu-host"
    assert state.embedding_backend == "gpu-host"


def test_unknown_embedder_key_resolves_to_the_default() -> None:
    choices = catalogue("fake-embedder", "gpu-host")

    assert choices.resolve("gone").key == "fake-embedder"
    assert choices.resolve(None).key == "fake-embedder"
    assert choices.is_known("gpu-host")


async def test_run_revision_without_a_snapshot_gets_one_queued() -> None:
    """Индекс на другой ревизии ревью не использует — дело получает свой снимок."""
    unit_of_work = FakeUnitOfWork()
    tenant_id, repository_id = prepare(unit_of_work)
    vcs_provider = FakeVcsProvider(
        tree={"app/report.py": ContentHash("hash-1")},
        file_contents={"app/report.py": MODULE},
    )
    await build(unit_of_work, vcs_provider, tenant_id, repository_id)
    ensure = EnsureIndexForRevision(unit_of_work, FakeEventPublisher(), vcs_provider)

    queued = await ensure.execute(tenant_id, repository_id, CommitSha("feature"))
    same_again = await ensure.execute(tenant_id, repository_id, CommitSha("feature"))

    assert queued is not None
    assert same_again is None
    async with unit_of_work:
        latest = await unit_of_work.index_snapshots.find_latest(repository_id)
    assert latest is not None
    assert latest.commit_sha == "sha-feature"
    assert latest.is_finished is False


async def test_run_revision_already_indexed_queues_nothing() -> None:
    unit_of_work = FakeUnitOfWork()
    tenant_id, repository_id = prepare(unit_of_work)
    vcs_provider = FakeVcsProvider(
        tree={"app/report.py": ContentHash("hash-1")},
        file_contents={"app/report.py": MODULE},
    )
    await build(unit_of_work, vcs_provider, tenant_id, repository_id)
    async with unit_of_work:
        ready = await unit_of_work.index_snapshots.find_latest_ready(repository_id)
    assert ready is not None

    queued = await EnsureIndexForRevision(unit_of_work, FakeEventPublisher(), vcs_provider).execute(
        tenant_id, repository_id, ready.commit_sha
    )

    assert queued is None
