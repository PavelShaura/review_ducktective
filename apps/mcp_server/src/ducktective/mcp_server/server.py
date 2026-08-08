from collections.abc import (
    Awaitable,
    Callable,
)
from dataclasses import (
    dataclass,
)

from mcp.server.mcpserver import (
    MCPServer,
)

from ducktective.application.code_repository.resolve import (
    RepositoryNotResolvedError,
    ResolveCodeRepository,
)
from ducktective.application.exceptions import (
    PermissionDeniedError,
)
from ducktective.application.indexing.read_state import (
    GetIndexState,
)
from ducktective.application.indexing.views import (
    IndexStateView,
)
from ducktective.application.retrieval.read_index import (
    NavigateCode,
    SurveyRepositories,
)
from ducktective.core.types import (
    RepositoryId,
)
from ducktective.mcp_server.rendering import (
    MAX_ANSWER_CHARS,
    clipped,
    describe_index,
    render_answer,
    render_repositories,
)
from ducktective.mcp_server.runtime import (
    McpRuntime,
)


INSTRUCTIONS = """Навигация по кодовой базе, проиндексированной Ducktective.

Символы, граф вызовов и фрагменты кода читаются из индекса, а не с диска,
поэтому ответы описывают зафиксированную ревизию: незакоммиченных правок
в них нет. Ревизия названа в конце каждого ответа.

Репозиторий называется именем или идентификатором; список даёт
list_repositories. История коммитов, авторы и рабочая копия сюда не входят."""


@dataclass(frozen=True, kw_only=True)
class _Target:
    """Репозиторий вместе с состоянием индекса, прочитанным один раз."""

    repository_id: RepositoryId
    index: IndexStateView


_Action = Callable[[_Target], Awaitable[str]]


def build_server(runtime: McpRuntime) -> MCPServer:
    """Собирает сервер поверх готовых зависимостей.

    Зависимости приходят снаружи, а не создаются здесь: движок базы должен
    рождаться в том же цикле событий, в котором работает сервер.
    """
    server = MCPServer(
        name="ducktective",
        version="0.1.0",
        instructions=INSTRUCTIONS,
    )

    @server.tool()
    async def list_repositories() -> str:
        """Перечисляет доступные репозитории и состояние их индексов.

        С этого стоит начинать: остальные инструменты требуют имя репозитория,
        а отвечает он, только когда индекс собран.
        """
        overviews = await SurveyRepositories(runtime.unit_of_work()).execute(runtime.tenant_id)
        return render_repositories(overviews)

    @server.tool()
    async def search_code(repository: str, query: str, limit: int = 10) -> str:
        """Ищет фрагменты кода по смыслу и по словам одновременно.

        Запрос — свободный текст: имя функции, название понятия или описание
        поведения. Возвращает фрагменты с путём и номерами строк.
        """
        return await _guarded(
            runtime,
            repository,
            lambda target: _search(runtime, target, query, limit),
        )

    @server.tool()
    async def get_definition(repository: str, name: str, limit: int = 5) -> str:
        """Показывает определение символа целиком.

        Имя — полное (`ReviewRun.add_finding`) или короткое (`add_finding`).
        Одноимённые символы возвращаются все: выбор за спрашивающим.
        """
        return await _guarded(
            runtime,
            repository,
            lambda target: _definition(runtime, target, name, limit),
        )

    @server.tool()
    async def find_callers(repository: str, name: str, limit: int = 20) -> str:
        """Показывает, откуда вызывается символ.

        Отвечает на вопрос «что сломается, если это изменить». Вызывающие
        приходят сигнатурой и местом, без тела.
        """
        return await _guarded(
            runtime,
            repository,
            lambda target: _callers(runtime, target, name, limit),
        )

    @server.tool()
    async def get_file_context(
        repository: str,
        path: str,
        start_line: int,
        end_line: int,
        neighbours_limit: int = 10,
    ) -> str:
        """Показывает окружение участка файла.

        Участок задаётся строками, ответ приходит символами: какие определения
        покрывают эти строки, что они вызывают и кто вызывает их.
        """
        return await _guarded(
            runtime,
            repository,
            lambda target: _file_context(
                runtime,
                target,
                path,
                start_line,
                end_line,
                neighbours_limit,
            ),
        )

    return server


async def _search(runtime: McpRuntime, target: _Target, query: str, limit: int) -> str:
    answer = await _navigation(runtime).search_code(
        runtime.tenant_id,
        target.repository_id,
        query,
        limit=limit,
    )
    return render_answer(answer, empty_message=f"По запросу «{query}» ничего не нашлось")


async def _definition(runtime: McpRuntime, target: _Target, name: str, limit: int) -> str:
    answer = await _navigation(runtime).get_definition(
        runtime.tenant_id,
        target.repository_id,
        name,
        limit=limit,
    )
    return render_answer(answer, empty_message=f"Символ «{name}» не найден")


async def _callers(runtime: McpRuntime, target: _Target, name: str, limit: int) -> str:
    answer = await _navigation(runtime).find_callers(
        runtime.tenant_id,
        target.repository_id,
        name,
        limit=limit,
    )
    return render_answer(answer, empty_message=f"Вызовов «{name}» не найдено")


async def _file_context(
    runtime: McpRuntime,
    target: _Target,
    path: str,
    start_line: int,
    end_line: int,
    neighbours_limit: int,
) -> str:
    answer = await _navigation(runtime).get_file_context(
        runtime.tenant_id,
        target.repository_id,
        path,
        start_line=start_line,
        end_line=end_line,
        limit=neighbours_limit,
    )
    return render_answer(
        answer,
        empty_message=f"В {path}:{start_line}-{end_line} показывать нечего",
    )


def _navigation(runtime: McpRuntime) -> NavigateCode:
    return NavigateCode(runtime.unit_of_work(), runtime.navigators)


async def _guarded(runtime: McpRuntime, reference: str, action: _Action) -> str:
    """Разрешает репозиторий, выполняет запрос и подписывает ответ ревизией.

    Ошибки возвращаются текстом, а не исключением: для вызывающей модели
    «репозиторий назван неверно, вот доступные» — это полезный ответ,
    а протокольная ошибка — тупик.

    Состояние индекса читается здесь один раз и служит двум целям: объяснить
    пустой ответ и подписать непустой. Пустая выдача по несобранному индексу
    неотличима от честного «нет такого», а непустая без ревизии не позволяет
    судить, насколько она свежа.
    """
    unit_of_work = runtime.unit_of_work()
    try:
        repository = await ResolveCodeRepository(unit_of_work).execute(runtime.tenant_id, reference)
    except RepositoryNotResolvedError as error:
        available = ", ".join(error.available) or "ни одного"
        return f"Репозиторий «{error.reference}» не найден. Доступны: {available}"
    except PermissionDeniedError as error:
        return str(error)

    state = await GetIndexState(unit_of_work).execute(runtime.tenant_id, repository.id)
    answer = await action(_Target(repository_id=repository.id, index=state))

    return f"{clipped(answer, MAX_ANSWER_CHARS)}\n\n— {repository.name}: {describe_index(state)}"
