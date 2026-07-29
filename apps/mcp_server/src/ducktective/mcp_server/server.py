from collections.abc import (
    Awaitable,
    Callable,
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
from ducktective.application.retrieval.read_index import (
    FindSymbolCallers,
    GetFileContext,
    GetSymbolDefinition,
    SearchCode,
)
from ducktective.core.types import (
    RepositoryId,
)
from ducktective.mcp_server.rendering import (
    render_contracts,
    render_definitions,
    render_matches,
    render_neighbourhood,
)
from ducktective.mcp_server.runtime import (
    McpRuntime,
)


_Action = Callable[[RepositoryId], Awaitable[str]]

INSTRUCTIONS = """Навигация по кодовой базе, проиндексированной Ducktective.

Символы, граф вызовов и фрагменты кода читаются из индекса, а не с диска,
поэтому ответы отражают состояние последней индексации репозитория.
Репозиторий называется именем или идентификатором."""


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
    async def search_code(repository: str, query: str, limit: int = 10) -> str:
        """Ищет фрагменты кода по смыслу и по словам одновременно.

        Запрос — свободный текст: имя функции, название понятия или описание
        поведения. Возвращает фрагменты с путём и номерами строк.
        """
        return await _guarded(
            runtime,
            repository,
            lambda repository_id: _search(runtime, repository_id, query, limit),
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
            lambda repository_id: _definition(runtime, repository_id, name, limit),
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
            lambda repository_id: _callers(runtime, repository_id, name, limit),
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
            lambda repository_id: _file_context(
                runtime,
                repository_id,
                path,
                start_line,
                end_line,
                neighbours_limit,
            ),
        )

    return server


async def _search(runtime: McpRuntime, repository_id: RepositoryId, query: str, limit: int) -> str:
    use_case = SearchCode(runtime.unit_of_work(), runtime.search)
    matches = await use_case.execute(runtime.tenant_id, repository_id, query, limit=limit)
    if not matches:
        return await _nothing_found(
            runtime, repository_id, f"По запросу «{query}» ничего не нашлось"
        )
    return render_matches(matches)


async def _definition(
    runtime: McpRuntime,
    repository_id: RepositoryId,
    name: str,
    limit: int,
) -> str:
    use_case = GetSymbolDefinition(runtime.unit_of_work(), runtime.symbols)
    symbols = await use_case.execute(runtime.tenant_id, repository_id, name, limit=limit)
    if not symbols:
        return await _nothing_found(runtime, repository_id, f"Символ «{name}» в индексе не найден")
    return render_definitions(symbols)


async def _callers(
    runtime: McpRuntime,
    repository_id: RepositoryId,
    name: str,
    limit: int,
) -> str:
    use_case = FindSymbolCallers(runtime.unit_of_work(), runtime.symbols)
    callers = await use_case.execute(runtime.tenant_id, repository_id, name, limit=limit)
    if not callers:
        return await _nothing_found(
            runtime,
            repository_id,
            f"Вызовов «{name}» в индексе нет",
        )
    return render_contracts(callers)


async def _file_context(
    runtime: McpRuntime,
    repository_id: RepositoryId,
    path: str,
    start_line: int,
    end_line: int,
    neighbours_limit: int,
) -> str:
    use_case = GetFileContext(runtime.unit_of_work(), runtime.symbols)
    view = await use_case.execute(
        runtime.tenant_id,
        repository_id,
        path,
        start_line=start_line,
        end_line=end_line,
        neighbours_limit=neighbours_limit,
    )
    if view.is_empty:
        return await _nothing_found(
            runtime,
            repository_id,
            f"В {path}:{start_line}-{end_line} проиндексированных символов нет",
        )
    return render_neighbourhood(view)


async def _guarded(
    runtime: McpRuntime,
    reference: str,
    action: _Action,
) -> str:
    """Разрешает репозиторий и выполняет запрос.

    Ошибки возвращаются текстом, а не исключением: для вызывающей модели
    «репозиторий назван неверно, вот доступные» — это полезный ответ,
    а протокольная ошибка — тупик.
    """
    try:
        repository = await ResolveCodeRepository(runtime.unit_of_work()).execute(
            runtime.tenant_id,
            reference,
        )
    except RepositoryNotResolvedError as error:
        available = ", ".join(error.available) or "ни одного"
        return f"Репозиторий «{error.reference}» не найден. Доступны: {available}"
    except PermissionDeniedError as error:
        return str(error)

    return await action(repository.id)


async def _nothing_found(runtime: McpRuntime, repository_id: RepositoryId, message: str) -> str:
    """Объясняет пустой ответ несобранным индексом, если дело в нём.

    Пустая выдача по несобранному индексу неотличима от честного «нет такого»,
    и без этой проверки клиент сделал бы неверный вывод о коде.
    """
    state = await GetIndexState(runtime.unit_of_work()).execute(runtime.tenant_id, repository_id)
    if state.is_ready:
        return message
    if state.is_running:
        return f"{message}. Индекс репозитория ещё собирается"
    return f"{message}. Индекс репозитория не собран"
