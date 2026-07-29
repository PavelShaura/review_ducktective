from ducktective.application.indexing.views import (
    IndexStateView,
)
from ducktective.application.retrieval.views import (
    CodeMatchView,
    RepositoryOverview,
    SymbolNeighbourhoodView,
    SymbolView,
)


MAX_FRAGMENT_CHARS = 4000
"""Предел одного фрагмента в ответе.

Индекс не обязан состоять из ровных кусков: файл без определений даёт чанк
на весь себя, и такой фрагмент, попав в выдачу, приносит с собой файл целиком.
Инструмент отвечает вызывающей модели, у которой окно контекста конечно,
поэтому предел стоит здесь, а не только там, где чанки нарезаются.
"""

MAX_ANSWER_CHARS = 24000
"""Предел всего ответа: пять урезанных фрагментов — это тоже много."""


def render_matches(matches: list[CodeMatchView]) -> str:
    blocks = [
        f"## {match.location}\n{match.breadcrumb}\n\n```\n{clipped(match.content.rstrip())}\n```"
        for match in matches
    ]
    return "\n\n".join(blocks)


def render_definitions(symbols: list[SymbolView]) -> str:
    return "\n\n".join(_definition(symbol) for symbol in symbols)


def render_contracts(symbols: list[SymbolView]) -> str:
    return "\n".join(_contract(symbol) for symbol in symbols)


def render_neighbourhood(view: SymbolNeighbourhoodView) -> str:
    sections = [
        f"# {view.path}:{view.start_line}-{view.end_line}",
        render_definitions(list(view.symbols)),
    ]
    if view.callees:
        sections.append(f"## Вызывает\n{render_contracts(list(view.callees))}")
    if view.callers:
        sections.append(f"## Вызывается из\n{render_contracts(list(view.callers))}")
    return "\n\n".join(sections)


def render_repositories(overviews: list[RepositoryOverview]) -> str:
    if not overviews:
        return "Ни одного репозитория не зарегистрировано"

    lines = [f"- {overview.name} — {describe_index(overview.index)}" for overview in overviews]
    return "\n".join(lines)


def describe_index(state: IndexStateView) -> str:
    """Описывает состояние индекса словами, а не полями.

    Ответы инструментов описывают зафиксированную ревизию, а не рабочую копию,
    и без этой строки спрашивающий не может отличить «в коде такого нет» от
    «этого не было на момент сборки индекса».
    """
    if state.is_running:
        return "индекс собирается"
    if not state.is_ready or state.commit_sha is None:
        return "индекс не собран"

    revision = state.commit_sha[:8]
    if state.finished_at is None:
        return f"индекс на ревизии {revision}"
    return f"индекс на ревизии {revision}, собран {state.finished_at:%Y-%m-%d %H:%M}"


def clipped(text: str, limit: int = MAX_FRAGMENT_CHARS) -> str:
    if len(text) <= limit:
        return text

    remainder = len(text) - limit
    return f"{text[:limit].rstrip()}\n… обрезано, ещё {remainder} символов"


def _definition(symbol: SymbolView) -> str:
    header = f"## {symbol.qualified_name} · {symbol.kind.value} · {symbol.location}"
    body = symbol.text.rstrip() or (symbol.signature or "")
    return f"{header}\n\n```\n{clipped(body)}\n```"


def _contract(symbol: SymbolView) -> str:
    signature = symbol.signature or symbol.qualified_name
    return f"- {symbol.qualified_name} — `{signature}` — {symbol.location}"
