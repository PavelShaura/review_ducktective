from ducktective.application.retrieval.views import (
    CodeMatchView,
    SymbolNeighbourhoodView,
    SymbolView,
)


def render_matches(matches: list[CodeMatchView]) -> str:
    blocks = [
        f"## {match.location}\n{match.breadcrumb}\n\n```\n{match.content.rstrip()}\n```"
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


def _definition(symbol: SymbolView) -> str:
    header = f"## {symbol.qualified_name} · {symbol.kind.value} · {symbol.location}"
    body = symbol.text.rstrip() or (symbol.signature or "")
    return f"{header}\n\n```\n{body}\n```"


def _contract(symbol: SymbolView) -> str:
    signature = symbol.signature or symbol.qualified_name
    return f"- {symbol.qualified_name} — `{signature}` — {symbol.location}"
