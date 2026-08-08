from ducktective.application.indexing.views import (
    IndexStateView,
)
from ducktective.application.retrieval.views import (
    RepositoryOverview,
)
from ducktective.core.retrieval.navigation import (
    CodeFragment,
    FragmentRole,
    NavigationAnswer,
)


MAX_ANSWER_CHARS = 24000
"""Предел всего ответа: пять урезанных фрагментов — это тоже много.

Предел одного фрагмента стоит в навигаторе: это его обещание. Здесь стоит
предел на выдачу целиком — инструмент не имеет права вернуть сто тысяч
символов ни при каком содержимом источника.
"""


ROLE_TITLES = {
    FragmentRole.CALLEE: "Вызывает",
    FragmentRole.CALLER: "Вызывается из",
}


def render_answer(answer: NavigationAnswer, *, empty_message: str) -> str:
    """Собирает ответ инструмента: оговорка сверху, фрагменты следом.

    Оговорка идёт первой строкой, а не сноской в конце: она меняет то, как
    читать выдачу, и прочитанная после фрагментов уже ничего не меняет.

    Соседи по графу собираются под своими заголовками: «что вызывает» и «кто
    вызывает» отвечают на разные вопросы, и без заголовка их различает только
    тот, кто и так знает код.
    """
    sections = []
    if answer.note:
        sections.append(answer.note)

    if answer.is_empty:
        sections.append(empty_message)
        return "\n\n".join(sections)

    for role in FragmentRole:
        fragments = answer.of_role(role)
        if not fragments:
            continue

        title = ROLE_TITLES.get(role)
        if title:
            sections.append(f"# {title}")
        sections.extend(_fragment(fragment) for fragment in fragments)

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


def clipped(text: str, limit: int = MAX_ANSWER_CHARS) -> str:
    if len(text) <= limit:
        return text

    remainder = len(text) - limit
    return f"{text[:limit].rstrip()}\n… обрезано, ещё {remainder} символов"


def _fragment(fragment: CodeFragment) -> str:
    title = f"{fragment.title} · " if fragment.title else ""
    return f"## {title}{fragment.location}\n\n```\n{fragment.text}\n```"
