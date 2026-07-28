import argparse
import asyncio
import json
from collections.abc import (
    AsyncIterator,
)
from contextlib import (
    asynccontextmanager,
)
from dataclasses import (
    dataclass,
)
from pathlib import (
    Path,
)
from time import (
    perf_counter,
)
from uuid import (
    UUID,
    uuid4,
)

import uvicorn
from redis.asyncio import (
    Redis,
)
from rich.console import (
    Console,
)
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
)

from ducktective.api.rendering import (
    render_index_outcome,
    render_markdown,
    render_outcome_notes,
    render_run,
)
from ducktective.application.indexing.build_embeddings import (
    BuildEmbeddings,
    EmbeddingOutcome,
)
from ducktective.application.indexing.build_index import (
    BuildIndex,
    BuildIndexCommand,
)
from ducktective.application.review.prepare_run import (
    EmptyDiffError,
    NoMatchingFilesError,
    PrepareReviewRun,
    PrepareReviewRunCommand,
)
from ducktective.application.review.run_review import (
    RunReview,
)
from ducktective.config.settings import (
    Settings,
)
from ducktective.core.code_repository.entities import (
    CodeRepository,
)
from ducktective.core.code_repository.value_objects import (
    EgressPolicy,
    VcsProvider,
)
from ducktective.core.exceptions import (
    DomainError,
    LlmInvocationError,
)
from ducktective.core.ports import (
    EventPublisher,
    UnitOfWork,
)
from ducktective.core.retrieval.ports import (
    ContextBuilder,
)
from ducktective.core.review.entities import (
    ReviewRun,
)
from ducktective.core.review.value_objects import (
    FindingStatus,
    Severity,
)
from ducktective.core.types import (
    RepositoryId,
    TenantId,
)
from ducktective.evals.cases import (
    EvalDataset,
    load_dataset,
)
from ducktective.evals.harness import (
    EvaluationHarness,
    EvaluationOutcome,
)
from ducktective.evals.reporting import (
    render_evaluation,
)
from ducktective.evals.store import (
    SqlAlchemyEvalStore,
)
from ducktective.indexing.python_parser import (
    PythonParser,
)
from ducktective.llm.code_reviewer import (
    SINGLE_PASS_PROMPT_FILE,
    LlmCodeReviewer,
    load_prompt,
)
from ducktective.llm.embedder import (
    LiteLlmEmbedder,
)
from ducktective.llm.factory import (
    build_code_reviewer,
)
from ducktective.retrieval.session_scope import (
    SessionScopedContextBuilder,
)
from ducktective.storage.database import (
    build_engine,
    build_session_factory,
)
from ducktective.storage.events.null_publisher import (
    NullEventPublisher,
)
from ducktective.storage.events.redis_publisher import (
    RedisEventPublisher,
)
from ducktective.storage.memory.unit_of_work import (
    InMemoryUnitOfWork,
)
from ducktective.storage.repositories.code_repository import (
    SqlAlchemyCodeRepositoryRepository,
)
from ducktective.storage.unit_of_work import (
    SqlAlchemyUnitOfWork,
)
from ducktective.vcs.diff_parser import (
    UnifiedDiffParser,
)
from ducktective.vcs.git_provider import (
    LocalGitProvider,
)


console = Console()
error_console = Console(stderr=True)

SEVERITY_RANK = {
    Severity.NITPICK: 1,
    Severity.MINOR: 2,
    Severity.MAJOR: 3,
    Severity.CRITICAL: 4,
}


@dataclass
class ReviewContext:
    unit_of_work: UnitOfWork
    event_publisher: EventPublisher
    code_reviewer: LlmCodeReviewer
    context_builder: ContextBuilder | None = None


def main() -> None:
    parser = argparse.ArgumentParser(prog="ducktective")
    subcommands = parser.add_subparsers(dest="command", required=True)

    serve_parser = subcommands.add_parser("serve", help="Запустить API")
    serve_parser.add_argument("--host", default="127.0.0.1")
    serve_parser.add_argument("--port", type=int, default=8000)
    serve_parser.add_argument("--reload", action="store_true")

    review_parser = subcommands.add_parser("review", help="Проревьюить дифф локально")
    review_parser.add_argument("path", type=Path, nargs="?", default=Path())
    review_parser.add_argument("--base", default="HEAD~1")
    review_parser.add_argument("--head", default="HEAD")
    review_parser.add_argument(
        "--staged",
        action="store_true",
        help="Ревьюить проиндексированные изменения вместо диапазона ревизий",
    )
    review_parser.add_argument(
        "--no-store",
        action="store_true",
        help="Не использовать базу и Redis: прогон целиком в памяти процесса",
    )
    review_parser.add_argument("--tenant", help="Идентификатор тенанта; не нужен с --no-store")
    review_parser.add_argument(
        "--include",
        action="append",
        metavar="ШАБЛОН",
        help="Ревьюить только совпавшие пути; можно указать несколько раз",
    )
    review_parser.add_argument(
        "--allow-cloud",
        action="store_true",
        help="Разрешить облачные модели для этого репозитория",
    )
    review_parser.add_argument(
        "--format",
        choices=["rich", "json", "markdown"],
        default="rich",
        help="Формат вывода",
    )
    review_parser.add_argument(
        "--fail-on",
        choices=[severity.value for severity in Severity],
        help="Вернуть ненулевой код, если есть находки этого уровня или выше",
    )

    index_parser = subcommands.add_parser("index", help="Проиндексировать репозиторий")
    index_parser.add_argument("path", type=Path, nargs="?", default=Path())
    index_parser.add_argument("--revision", default="HEAD", help="Ревизия для индексации")
    index_parser.add_argument(
        "--no-store",
        action="store_true",
        help="Не использовать базу и Redis: индекс живёт в памяти процесса",
    )
    index_parser.add_argument("--tenant", help="Идентификатор тенанта; не нужен с --no-store")
    index_parser.add_argument(
        "--skip-embeddings",
        action="store_true",
        help="Не считать векторы: разбор кода и граф символов модели не требуют",
    )

    eval_parser = subcommands.add_parser("eval", help="Прогнать набор оценки качества")
    eval_parser.add_argument("dataset", type=Path, help="Файл с набором случаев")
    eval_parser.add_argument("--label", default="baseline", help="Метка прогона")
    eval_parser.add_argument(
        "--repository",
        type=Path,
        help="Проиндексированный репозиторий: включает контекст из индекса",
    )
    eval_parser.add_argument("--tenant", help="Тенант владельца репозитория")
    eval_parser.add_argument(
        "--repeat",
        type=int,
        default=1,
        help="Сколько раз прогнать набор: модель отвечает по-разному",
    )
    eval_parser.add_argument(
        "--save",
        action="store_true",
        help="Записать прогон в базу, чтобы было с чем сравнивать дальше",
    )

    arguments = parser.parse_args()

    if arguments.command == "eval":
        raise SystemExit(asyncio.run(_evaluate(arguments)))

    if arguments.command == "index":
        raise SystemExit(asyncio.run(_index(arguments)))

    if arguments.command == "serve":
        uvicorn.run(
            "ducktective.api.main:app",
            host=arguments.host,
            port=arguments.port,
            reload=arguments.reload,
        )
        return

    if arguments.command == "review":
        raise SystemExit(asyncio.run(_review(arguments)))


async def _review(arguments: argparse.Namespace) -> int:
    settings = Settings()
    repository_path = arguments.path.resolve()
    tenant_id = _resolve_tenant(arguments)
    egress_policy = EgressPolicy.ALLOW_CLOUD if arguments.allow_cloud else EgressPolicy.LOCAL_ONLY

    try:
        async with _build_context(settings, no_store=arguments.no_store) as context:
            repository_id = await _ensure_repository(
                context.unit_of_work,
                tenant_id=tenant_id,
                repository_path=repository_path,
                egress_policy=egress_policy,
            )

            with console.status("[dim]Собираю дифф…[/]", spinner="dots"):
                prepared = await PrepareReviewRun(
                    context.unit_of_work,
                    context.event_publisher,
                    LocalGitProvider(),
                    UnifiedDiffParser(),
                ).execute(
                    PrepareReviewRunCommand(
                        tenant_id=tenant_id,
                        repository_id=repository_id,
                        base=arguments.base,
                        head=arguments.head,
                        staged=arguments.staged,
                        include_patterns=tuple(arguments.include or ()),
                    )
                )

            file_count = len(prepared.reviewable_files())
            with console.status(
                f"[dim]Ревьюю {file_count} файл(ов), это может занять минуты…[/]",
                spinner="dots",
            ):
                outcome = await RunReview(
                    context.unit_of_work,
                    context.event_publisher,
                    context.code_reviewer,
                    context.context_builder,
                ).execute(tenant_id, prepared.id)
                run = outcome.run
    except (EmptyDiffError, NoMatchingFilesError) as error:
        error_console.print(f"[yellow]{error}[/]")
        return 0
    except (DomainError, ValueError) as error:
        error_console.print(f"[red]Ошибка:[/] {error}")
        return 1

    _render(run, output_format=arguments.format)
    if arguments.format == "rich":
        render_outcome_notes(console, outcome)
    return _exit_code(run, arguments.fail_on)


async def _evaluate(arguments: argparse.Namespace) -> int:
    """Прогоняет набор случаев с известными ответами.

    Контекст подключается только когда указан проиндексированный репозиторий:
    прогон без него и есть точка отсчёта, с которой сравнивается всё
    последующее.
    """
    settings = Settings()
    dataset = load_dataset(arguments.dataset)

    engine = None
    context_builder: ContextBuilder | None = None
    indexed_repository_id: RepositoryId | None = None
    if arguments.repository:
        engine = build_engine(settings.require_database_url())
        session_factory = build_session_factory(engine)
        context_builder = _build_context_builder(settings, session_factory)
        indexed_repository_id = await _find_indexed_repository(
            session_factory,
            _resolve_tenant(arguments),
            arguments.repository.resolve().name,
        )

    try:
        harness = EvaluationHarness(
            _build_reviewer(settings, redis_client=None),
            UnifiedDiffParser(),
            context_builder=context_builder,
            indexed_repository_id=indexed_repository_id,
        )
        with console.status(
            f"[dim]Прогоняю {len(dataset.cases)} случаев × {arguments.repeat}…[/]",
            spinner="dots",
        ):
            outcome = await harness.run(
                dataset,
                label=arguments.label,
                repeats=arguments.repeat,
            )
    except (DomainError, ValueError) as error:
        error_console.print(f"[red]Ошибка:[/] {error}")
        return 1
    finally:
        if engine is not None:
            await engine.dispose()

    render_evaluation(console, outcome)

    if arguments.save:
        await _save_evaluation(settings, dataset, outcome)
        console.print("[dim]прогон записан[/]")

    return 0


async def _find_indexed_repository(
    session_factory: async_sessionmaker[AsyncSession],
    tenant_id: TenantId,
    name: str,
) -> RepositoryId:
    """Находит репозиторий, для которого построен индекс."""
    async with session_factory() as session:
        unit_of_work_repository = SqlAlchemyCodeRepositoryRepository(session)
        repository = await unit_of_work_repository.find_by_name(tenant_id, name)

    if repository is None:
        raise ValueError(f"Репозиторий «{name}» не зарегистрирован — сначала ducktective index")
    return repository.id


async def _save_evaluation(
    settings: Settings,
    dataset: EvalDataset,
    outcome: EvaluationOutcome,
) -> None:
    engine = build_engine(settings.require_database_url())
    try:
        async with build_session_factory(engine)() as session:
            await SqlAlchemyEvalStore(session).save(
                dataset,
                outcome,
                model=settings.local_review_model,
                prompt=load_prompt(SINGLE_PASS_PROMPT_FILE),
                prompt_name=SINGLE_PASS_PROMPT_FILE,
            )
            await session.commit()
    finally:
        await engine.dispose()


async def _index(arguments: argparse.Namespace) -> int:
    settings = Settings()
    repository_path = arguments.path.resolve()
    tenant_id = _resolve_tenant(arguments)

    try:
        async with _build_context(settings, no_store=arguments.no_store) as context:
            repository_id = await _ensure_repository(
                context.unit_of_work,
                tenant_id=tenant_id,
                repository_path=repository_path,
                egress_policy=EgressPolicy.LOCAL_ONLY,
            )

            started = perf_counter()
            with console.status("[dim]Разбираю кодовую базу…[/]", spinner="dots"):
                outcome = await BuildIndex(
                    context.unit_of_work,
                    context.event_publisher,
                    LocalGitProvider(),
                    PythonParser(),
                ).execute(
                    BuildIndexCommand(
                        tenant_id=tenant_id,
                        repository_id=repository_id,
                        revision=arguments.revision,
                    )
                )
            embeddings = None
            if not arguments.skip_embeddings:
                embeddings = await _embed(context.unit_of_work, settings, repository_id)
            elapsed = perf_counter() - started
    except (DomainError, ValueError) as error:
        error_console.print(f"[red]Ошибка:[/] {error}")
        return 1

    render_index_outcome(console, outcome, embeddings, elapsed_seconds=elapsed)
    return 0


async def _embed(
    unit_of_work: UnitOfWork,
    settings: Settings,
    repository_id: RepositoryId,
) -> EmbeddingOutcome | None:
    """Считает недостающие векторы.

    Недоступность модели не отменяет уже построенный индекс: разбор кода
    и граф символов от неё не зависят, поэтому ошибка сообщается, а прогон
    считается состоявшимся.
    """
    embedder = LiteLlmEmbedder(
        model=settings.local_embedding_model,
        dimensions=settings.embedding_dimensions,
        base_url=settings.local_embedding_base_url or None,
        api_key=settings.local_llm_api_key,
    )

    try:
        with console.status("[dim]Считаю векторы…[/]", spinner="dots"):
            return await BuildEmbeddings(unit_of_work, embedder).execute(repository_id)
    except LlmInvocationError as error:
        error_console.print(f"[yellow]Векторы не посчитаны:[/] {error}")
        return None


@asynccontextmanager
async def _build_context(settings: Settings, *, no_store: bool) -> AsyncIterator[ReviewContext]:
    """Собирает зависимости под выбранный режим.

    В автономном режиме внешних сервисов нет вообще: те же use cases получают
    Unit of Work на словарях и ревьюера без кэша.
    """
    if no_store:
        yield ReviewContext(
            unit_of_work=InMemoryUnitOfWork(),
            event_publisher=NullEventPublisher(),
            code_reviewer=_build_reviewer(settings, redis_client=None),
        )
        return

    engine = build_engine(settings.require_database_url())
    session_factory = build_session_factory(engine)
    redis_client = Redis.from_url(settings.require_redis_url(), decode_responses=True)
    try:
        yield ReviewContext(
            unit_of_work=SqlAlchemyUnitOfWork(session_factory),
            event_publisher=RedisEventPublisher(redis_client),
            code_reviewer=_build_reviewer(settings, redis_client=redis_client),
            context_builder=_build_context_builder(settings, session_factory),
        )
    finally:
        await redis_client.aclose()
        await engine.dispose()


def _build_context_builder(
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
) -> ContextBuilder:
    """Собирает ретривал поверх собственной сессии.

    Сессия отдельная от той, что держит Unit of Work: контекст читается,
    пока транзакция прогона закрыта, и делить одну сессию между ними значило бы
    открывать её раньше времени.
    """
    embedder = LiteLlmEmbedder(
        model=settings.local_embedding_model,
        dimensions=settings.embedding_dimensions,
        base_url=settings.local_embedding_base_url or None,
        api_key=settings.local_llm_api_key,
    )
    return SessionScopedContextBuilder(
        session_factory,
        embedder,
        token_budget=settings.context_token_budget,
    )


def _build_reviewer(settings: Settings, *, redis_client: Redis | None) -> LlmCodeReviewer:
    return build_code_reviewer(
        redis_client=redis_client,
        local_provider=settings.local_llm_provider,
        local_model=settings.local_review_model,
        local_base_url=settings.local_llm_base_url,
        local_api_key=settings.local_llm_api_key,
        cloud_model=settings.cloud_review_model,
        cloud_api_key=settings.anthropic_api_key,
        cloud_enabled=settings.cloud_providers_allowed,
        cache_ttl_seconds=settings.llm_cache_ttl_seconds,
        timeout_seconds=settings.llm_timeout_seconds,
    )


def _resolve_tenant(arguments: argparse.Namespace) -> TenantId:
    if arguments.tenant:
        return TenantId(UUID(arguments.tenant))
    if arguments.no_store:
        return TenantId(uuid4())
    raise SystemExit("Укажите --tenant или используйте --no-store")


async def _ensure_repository(
    unit_of_work: UnitOfWork,
    *,
    tenant_id: TenantId,
    repository_path: Path,
    egress_policy: EgressPolicy,
) -> RepositoryId:
    """Находит репозиторий по имени каталога или регистрирует новый."""
    name = repository_path.name

    async with unit_of_work:
        existing = await unit_of_work.code_repositories.find_by_name(tenant_id, name)
        if existing is not None:
            return existing.id

        repository = CodeRepository.register(
            tenant_id=tenant_id,
            name=name,
            vcs_provider=VcsProvider.LOCAL,
            local_path=repository_path,
            egress_policy=egress_policy,
        )
        unit_of_work.code_repositories.add(repository)
        await unit_of_work.commit()
        return repository.id


def _render(run: ReviewRun, *, output_format: str) -> None:
    if output_format == "json":
        console.print_json(json.dumps(_to_payload(run), ensure_ascii=False))
        return
    if output_format == "markdown":
        console.print(render_markdown(run), markup=False, highlight=False)
        return
    render_run(console, run)


def _exit_code(run: ReviewRun, fail_on: str | None) -> int:
    """Ненулевой код при находках нужного уровня — для pre-push хука и CI."""
    if not fail_on:
        return 0

    threshold = SEVERITY_RANK[Severity(fail_on)]
    worst = max(
        (
            SEVERITY_RANK[finding.severity]
            for finding in run.findings
            if finding.status is not FindingStatus.REJECTED
        ),
        default=0,
    )
    return 1 if worst >= threshold else 0


def _to_payload(run: ReviewRun) -> dict[str, object]:
    return {
        "run_id": str(run.id),
        "status": run.status.value,
        "base_sha": run.base_sha,
        "head_sha": run.head_sha,
        "totals": run.severity_totals,
        "tokens": {"input": run.tokens_input, "output": run.tokens_output},
        "cost_usd": round(run.cost_usd, 6),
        "findings": [
            {
                "file": finding.file_path,
                "line_start": finding.line_start,
                "line_end": finding.line_end,
                "severity": finding.severity.value,
                "category": finding.category.value,
                "title": finding.title,
                "body": finding.body_markdown,
                "suggested_patch": finding.suggested_patch,
            }
            for finding in run.findings
        ],
    }
