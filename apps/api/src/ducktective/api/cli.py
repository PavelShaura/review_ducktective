import argparse
import asyncio
import json
from collections.abc import (
    AsyncIterator,
    Sequence,
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
    uuid4,
)

import httpx
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

from ducktective.api.dependencies import (
    remote_model_choices,
)
from ducktective.api.dev import (
    plan,
    supervise,
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
from ducktective.application.tenancy.sign_in import (
    ResolveSignedInUser,
)
from ducktective.auth.device_flow import (
    DeviceAuthorization,
)
from ducktective.auth.oidc import (
    OidcIdentityVerifier,
    OidcSettings,
)
from ducktective.auth.session import (
    TerminalSession,
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
    NotAuthenticatedError,
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
from ducktective.core.review.ports import (
    CodeReviewer,
    ReviewNavigators,
    ReviewPipeline,
)
from ducktective.core.review.reviewers import (
    ReviewMode,
    reviewer_name,
)
from ducktective.core.review.value_objects import (
    FindingStatus,
    Severity,
)
from ducktective.core.tenancy.entities import (
    UserAccount,
)
from ducktective.core.types import (
    CommitSha,
    RepositoryId,
    TenantId,
)
from ducktective.evals.cases import (
    EvalDataset,
    load_dataset,
)
from ducktective.evals.harness import (
    EvalNavigators,
    EvaluationHarness,
    EvaluationOutcome,
    redirect_context,
)
from ducktective.evals.reporting import (
    render_evaluation,
)
from ducktective.evals.store import (
    SqlAlchemyEvalStore,
)
from ducktective.indexing.parsers import (
    build_parser,
)
from ducktective.llm.code_reviewer import (
    PROMPT_SET_NAME,
    system_prompt,
)
from ducktective.llm.embedder import (
    LiteLlmEmbedder,
)
from ducktective.llm.factory import (
    build_code_reviewers,
)
from ducktective.retrieval.navigation import (
    IndexedNavigators,
)
from ducktective.retrieval.session_scope import (
    SessionScopedContextBuilder,
    SessionScopedHybridSearch,
    SessionScopedSymbolReader,
)
from ducktective.review_graph import (
    LangGraphReviewPipeline,
)
from ducktective.review_graph.navigators import (
    RequestNavigators,
)
from ducktective.storage.cipher import (
    generate_secret_key,
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
from ducktective.storage.history import (
    PostgresFindingHistory,
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
from ducktective.vcs.navigation import (
    GitNavigators,
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
    pipeline: ReviewPipeline


def main() -> None:
    parser = argparse.ArgumentParser(prog="ducktective")
    subcommands = parser.add_subparsers(dest="command", required=True)

    dev_parser = subcommands.add_parser(
        "dev",
        help="Поднять всё разом: API, воркеры и фронт",
    )
    dev_parser.add_argument("--no-web", action="store_true", help="Без фронта")
    dev_parser.add_argument("--no-workers", action="store_true", help="Без воркеров")
    dev_parser.add_argument("--reload", action="store_true", help="Перезапускать API по правкам")

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
    eval_parser.add_argument(
        "--mode",
        choices=[mode.value for mode in ReviewMode],
        default=ReviewMode.AGENTIC.value,
        help="Каким ревьюером мерить: агентным или одним проходом",
    )
    eval_parser.add_argument(
        "--no-index",
        action="store_true",
        help="Мерить без индекса: контекст не собирается, инструменты ходят по git",
    )
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

    subcommands.add_parser(
        "login",
        help="Войти через провайдера личности: код подтверждается в браузере",
    )
    subcommands.add_parser("logout", help="Забыть сохранённый вход")
    subcommands.add_parser(
        "secret",
        help="Напечатать новый секрет шифрования ключей моделей (MODELS_SECRET_KEY)",
    )
    subcommands.add_parser("whoami", help="Показать, кто вошёл и в какой организации")

    arguments = parser.parse_args()

    if arguments.command == "login":
        raise SystemExit(asyncio.run(_login(arguments)))

    if arguments.command == "secret":
        console.print(generate_secret_key())
        return

    if arguments.command == "logout":
        raise SystemExit(asyncio.run(_logout(arguments)))

    if arguments.command == "whoami":
        raise SystemExit(asyncio.run(_whoami(arguments)))

    if arguments.command == "eval":
        raise SystemExit(asyncio.run(_evaluate(arguments)))

    if arguments.command == "index":
        raise SystemExit(asyncio.run(_index(arguments)))

    if arguments.command == "dev":
        raise SystemExit(asyncio.run(_dev(arguments)))

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


async def _dev(arguments: argparse.Namespace) -> int:
    """Поднимает всё разом, оставаясь тем же набором процессов.

    Воркеры не втягиваются в процесс API: разделение по профилю нагрузки
    закреплено решением D-013, и удобство запуска не повод его пересматривать.
    """
    services = plan(
        with_web=not arguments.no_web,
        with_workers=not arguments.no_workers,
        reload=arguments.reload,
    )
    return await supervise(services, console=console)


async def _review(arguments: argparse.Namespace) -> int:
    settings = Settings()
    repository_path = arguments.path.resolve()
    tenant_id = await _resolve_tenant(settings, arguments)
    egress_policy = EgressPolicy.ALLOW_CLOUD if arguments.allow_cloud else EgressPolicy.LOCAL_ONLY

    try:
        async with _build_context(
            settings,
            no_store=arguments.no_store,
            tenant_id=tenant_id,
        ) as context:
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
                    context.pipeline,
                    max_output_tokens=settings.llm_max_output_tokens,
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
    mode = ReviewMode(arguments.mode)
    with_index = bool(arguments.repository) and not arguments.no_index

    engine = None
    session_factory: async_sessionmaker[AsyncSession] | None = None
    context_builder: ContextBuilder | None = None
    indexed_repository_id: RepositoryId | None = None
    if with_index:
        engine = build_engine(settings.require_database_url())
        session_factory = build_session_factory(engine)
        eval_tenant = await _resolve_tenant(settings, arguments)
        context_builder = _build_context_builder(
            settings,
            session_factory,
            tenant_id=eval_tenant,
        )
        indexed_repository_id = await _find_indexed_repository(
            session_factory,
            eval_tenant,
            arguments.repository.resolve().name,
        )

    try:
        harness = EvaluationHarness(
            _build_pipeline(
                _build_reviewers(
                    settings,
                    redis_client=None,
                    agentic_enabled=mode is ReviewMode.AGENTIC,
                ),
                context_builder=redirect_context(context_builder, indexed_repository_id),
                session_factory=session_factory if with_index else None,
                settings=settings if with_index else None,
                navigators_for_eval=_eval_navigation(
                    arguments,
                    indexed_repository_id=indexed_repository_id,
                ),
            ),
            UnifiedDiffParser(),
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


def _prompt_set_text() -> str:
    """Подсказки обоих режимов одной записью.

    Прогон качества сравнивается с другим прогоном, и сравнивать его можно
    только зная, чем именно ревьюили. Ревьюер один (D-022), но подсказок
    у него две: агентная добавляет к общей части правила расследования,
    и прогон, где файлы читались по-разному, обязан опознаваться версией.
    """
    return "\n\n".join(
        f"# {reviewer_name(mode)}\n\n{system_prompt(with_tools=mode is ReviewMode.AGENTIC)}"
        for mode in ReviewMode
    )


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
                prompt=_prompt_set_text(),
                prompt_name=PROMPT_SET_NAME,
            )
            await session.commit()
    finally:
        await engine.dispose()


async def _index(arguments: argparse.Namespace) -> int:
    settings = Settings()
    repository_path = arguments.path.resolve()
    tenant_id = await _resolve_tenant(settings, arguments)

    try:
        async with _build_context(
            settings,
            no_store=arguments.no_store,
            tenant_id=tenant_id,
        ) as context:
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
                    build_parser(),
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
async def _build_context(
    settings: Settings,
    *,
    no_store: bool,
    tenant_id: TenantId,
) -> AsyncIterator[ReviewContext]:
    """Собирает зависимости под выбранный режим.

    В автономном режиме внешних сервисов нет вообще: те же use cases получают
    Unit of Work на словарях и ревьюера без кэша.
    """
    if no_store:
        yield ReviewContext(
            unit_of_work=InMemoryUnitOfWork(),
            event_publisher=NullEventPublisher(),
            pipeline=_build_pipeline(_build_reviewers(settings, redis_client=None)),
        )
        return

    engine = build_engine(settings.require_database_url())
    session_factory = build_session_factory(engine)
    redis_client = Redis.from_url(settings.require_redis_url(), decode_responses=True)
    try:
        yield ReviewContext(
            unit_of_work=SqlAlchemyUnitOfWork(session_factory, tenant_id=tenant_id),
            event_publisher=RedisEventPublisher(redis_client),
            pipeline=_build_pipeline(
                _build_reviewers(settings, redis_client=redis_client),
                context_builder=_build_context_builder(
                    settings,
                    session_factory,
                    tenant_id=tenant_id,
                ),
                session_factory=session_factory,
                settings=settings,
                tenant_id=tenant_id,
            ),
        )
    finally:
        await redis_client.aclose()
        await engine.dispose()


def _build_context_builder(
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    *,
    tenant_id: TenantId,
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
        tenant_id=tenant_id,
        token_budget=settings.context_token_budget,
    )


@dataclass(frozen=True, kw_only=True)
class _EvalNavigation:
    """Куда смотрят инструменты в прогоне набора.

    У случая набора нет ни своего репозитория, ни рабочего каталога, поэтому
    адрес подставляется снаружи: проиндексированный репозиторий для замера
    с индексом и настоящий каталог с ревизией — для замера без него.
    """

    repository_id: RepositoryId | None = None
    repository_path: Path | None = None
    revision: CommitSha | None = None
    index_revision: CommitSha | None = None


def _build_pipeline(
    reviewers: Sequence[CodeReviewer],
    *,
    context_builder: ContextBuilder | None = None,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
    settings: Settings | None = None,
    tenant_id: TenantId | None = None,
    navigators_for_eval: _EvalNavigation | None = None,
) -> ReviewPipeline:
    """Собирает конвейер вместе с тем, чем он будет ходить по коду.

    Навигация по git есть всегда — она не требует ни базы, ни индекса,
    и именно она делает агентный режим доступным автономному прогону
    (D-021). Индексная добавляется там, где база вообще открыта.
    """
    navigators: ReviewNavigators = RequestNavigators(
        indexed=_build_indexed_navigators(settings, session_factory, tenant_id=tenant_id),
        git=GitNavigators(git=LocalGitProvider()),
    )
    if navigators_for_eval is not None:
        navigators = EvalNavigators(
            navigators,
            repository_id=navigators_for_eval.repository_id,
            repository_path=navigators_for_eval.repository_path,
            revision=navigators_for_eval.revision,
            index_revision=navigators_for_eval.index_revision,
        )

    return LangGraphReviewPipeline(
        reviewers,
        context_builder=context_builder,
        navigators=navigators,
        history=(
            PostgresFindingHistory(session_factory, tenant_id=tenant_id)
            if session_factory
            else None
        ),
    )


def _eval_navigation(
    arguments: argparse.Namespace,
    *,
    indexed_repository_id: RepositoryId | None,
) -> _EvalNavigation | None:
    """Собирает адрес навигации под выбранный вариант замера."""
    if not arguments.repository:
        return None

    if indexed_repository_id is not None:
        return _EvalNavigation(
            repository_id=indexed_repository_id,
            revision=CommitSha("HEAD"),
            index_revision=CommitSha("HEAD"),
        )

    return _EvalNavigation(
        repository_path=arguments.repository.resolve(),
        revision=CommitSha("HEAD"),
    )


def _build_indexed_navigators(
    settings: Settings | None,
    session_factory: async_sessionmaker[AsyncSession] | None,
    *,
    tenant_id: TenantId | None = None,
) -> IndexedNavigators | None:
    if settings is None or session_factory is None:
        return None

    return IndexedNavigators(
        symbols=SessionScopedSymbolReader(session_factory, tenant_id=tenant_id),
        search=SessionScopedHybridSearch(
            session_factory,
            LiteLlmEmbedder(
                model=settings.local_embedding_model,
                dimensions=settings.embedding_dimensions,
                base_url=settings.local_embedding_base_url or None,
                api_key=settings.local_llm_api_key,
            ),
            tenant_id=tenant_id,
        ),
    )


def _build_reviewers(
    settings: Settings,
    *,
    redis_client: Redis | None,
    agentic_enabled: bool = True,
) -> tuple[CodeReviewer, ...]:
    return build_code_reviewers(
        agentic_enabled=agentic_enabled,
        redis_client=redis_client,
        local_provider=settings.local_llm_provider,
        local_model=settings.local_review_model,
        local_base_url=settings.local_llm_base_url,
        local_api_key=settings.local_llm_api_key,
        cloud_enabled=settings.cloud_providers_allowed,
        remote_choices=remote_model_choices(settings),
        cache_ttl_seconds=settings.llm_cache_ttl_seconds,
        timeout_seconds=settings.llm_timeout_seconds,
        local_supports_tools=settings.local_review_model_supports_tools,
        local_context_window=settings.local_review_model_context_window,
    )


def _terminal_session(settings: Settings) -> TerminalSession:
    if not settings.authentication_required:
        raise SystemExit(
            "Не задан OIDC_ISSUER: без провайдера личности терминал работает "
            "только в режиме --no-store"
        )
    return TerminalSession(
        issuer=settings.oidc_issuer,
        client_id=settings.oidc_device_client_id,
    )


async def _resolve_tenant(settings: Settings, arguments: argparse.Namespace) -> TenantId:
    """Организация берётся из членства вошедшего, а не из аргумента.

    Автономный режим тенанта не спрашивает вовсе: прогон живёт в памяти
    процесса, никуда не пишется и делить ему не с кем.
    """
    if getattr(arguments, "no_store", False):
        return TenantId(uuid4())

    account = await _resolve_membership(settings)
    return account.tenant_id


async def _resolve_membership(settings: Settings) -> UserAccount:
    session = _terminal_session(settings)
    try:
        token = await session.access_token()
    except NotAuthenticatedError as error:
        raise SystemExit(str(error)) from error

    engine = build_engine(settings.require_database_url())
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            verifier = OidcIdentityVerifier(
                OidcSettings(issuer=settings.oidc_issuer, audience=settings.oidc_audience),
                client,
            )
            try:
                identity = await verifier.verify(token)
            except NotAuthenticatedError as error:
                raise SystemExit(str(error)) from error

        resolved = await ResolveSignedInUser(
            SqlAlchemyUnitOfWork(build_session_factory(engine)),
            NullEventPublisher(),
        ).execute(identity)
    finally:
        await engine.dispose()

    if resolved.account is None:
        raise SystemExit(
            "Учётная запись не состоит в организации: создайте её в интерфейсе "
            "или примите приглашение"
        )
    return resolved.account


async def _login(arguments: argparse.Namespace) -> int:
    """Вход по device flow: код показывается здесь, подтверждение — в браузере."""
    settings = Settings()
    session = _terminal_session(settings)

    def announce(authorization: DeviceAuthorization) -> None:
        target = authorization.verification_uri_complete or authorization.verification_uri
        console.print(
            f"Откройте [bold]{target}[/] и введите код [bold]{authorization.user_code}[/]"
        )
        console.print("[dim]Жду подтверждения…[/]")

    try:
        await session.login(announce)
    except NotAuthenticatedError as error:
        error_console.print(f"[red]Вход не выполнен:[/] {error}")
        return 1

    account = await _resolve_membership(settings)
    console.print(f"[green]Вход выполнен:[/] {account.email} · роль {account.role}")
    return 0


async def _logout(arguments: argparse.Namespace) -> int:
    settings = Settings()
    if _terminal_session(settings).logout():
        console.print("Сохранённый вход удалён")
        return 0

    console.print("Сохранённого входа не было")
    return 0


async def _whoami(arguments: argparse.Namespace) -> int:
    settings = Settings()
    account = await _resolve_membership(settings)
    console.print(f"{account.email} · организация {account.tenant_id} · роль {account.role}")
    return 0


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


if __name__ == "__main__":
    main()
