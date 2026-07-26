import argparse
import asyncio
import json
from pathlib import (
    Path,
)
from uuid import (
    UUID,
)

import uvicorn
from redis.asyncio import (
    Redis,
)
from rich.console import (
    Console,
)

from ducktective.api.rendering import (
    render_run,
)
from ducktective.application.review.prepare_run import (
    EmptyDiffError,
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
)
from ducktective.core.review.entities import (
    ReviewRun,
)
from ducktective.core.types import (
    RepositoryId,
    TenantId,
)
from ducktective.llm.factory import (
    build_code_reviewer,
)
from ducktective.storage.database import (
    build_engine,
    build_session_factory,
)
from ducktective.storage.events.redis_publisher import (
    RedisEventPublisher,
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


def main() -> None:
    parser = argparse.ArgumentParser(prog="ducktective")
    subcommands = parser.add_subparsers(dest="command", required=True)

    serve_parser = subcommands.add_parser("serve", help="Запустить API")
    serve_parser.add_argument("--host", default="127.0.0.1")
    serve_parser.add_argument("--port", type=int, default=8000)
    serve_parser.add_argument("--reload", action="store_true")

    review_parser = subcommands.add_parser("review", help="Проревьюить дифф локально")
    review_parser.add_argument("path", type=Path, help="Путь к git-репозиторию")
    review_parser.add_argument("--tenant", required=True, help="Идентификатор тенанта")
    review_parser.add_argument("--base", default="HEAD~1")
    review_parser.add_argument("--head", default="HEAD")
    review_parser.add_argument(
        "--allow-cloud",
        action="store_true",
        help="Разрешить облачные модели для этого репозитория",
    )
    review_parser.add_argument("--json", action="store_true", help="Вывести результат как JSON")

    arguments = parser.parse_args()

    if arguments.command == "serve":
        uvicorn.run(
            "ducktective.api.main:app",
            host=arguments.host,
            port=arguments.port,
            reload=arguments.reload,
        )
        return

    if arguments.command == "review":
        asyncio.run(_review(arguments))


async def _review(arguments: argparse.Namespace) -> None:
    settings = Settings()
    engine = build_engine(settings.database_url)
    session_factory = build_session_factory(engine)
    redis_client = Redis.from_url(settings.redis_url, decode_responses=True)

    tenant_id = TenantId(UUID(arguments.tenant))
    repository_path = arguments.path.resolve()
    egress_policy = EgressPolicy.ALLOW_CLOUD if arguments.allow_cloud else EgressPolicy.LOCAL_ONLY

    unit_of_work = SqlAlchemyUnitOfWork(session_factory)
    publisher = RedisEventPublisher(redis_client)

    try:
        repository_id = await _ensure_repository(
            unit_of_work,
            tenant_id=tenant_id,
            repository_path=repository_path,
            egress_policy=egress_policy,
        )

        with console.status("[dim]Собираю дифф…[/]", spinner="dots"):
            prepared = await PrepareReviewRun(
                unit_of_work,
                publisher,
                LocalGitProvider(),
                UnifiedDiffParser(),
            ).execute(
                PrepareReviewRunCommand(
                    tenant_id=tenant_id,
                    repository_id=repository_id,
                    base=arguments.base,
                    head=arguments.head,
                )
            )

        reviewer = build_code_reviewer(
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

        file_count = len(prepared.reviewable_files())
        with console.status(
            f"[dim]Ревьюю {file_count} файл(ов), это может занять минуты…[/]",
            spinner="dots",
        ):
            run = await RunReview(unit_of_work, publisher, reviewer).execute(
                tenant_id,
                prepared.id,
            )
    except EmptyDiffError as error:
        error_console.print(f"[yellow]{error}[/]")
        return
    except DomainError as error:
        error_console.print(f"[red]Ошибка:[/] {error}")
        raise SystemExit(1) from error
    finally:
        await redis_client.aclose()
        await engine.dispose()

    if arguments.json:
        console.print_json(json.dumps(_to_payload(run), ensure_ascii=False))
    else:
        render_run(console, run)


async def _ensure_repository(
    unit_of_work: SqlAlchemyUnitOfWork,
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
