"""Перевод вопроса на язык, которым написан код.

Требование написано прозой, код написан идентификаторами, и общих слов
у них почти нет — особенно когда вопрос задан не на том языке, на котором
написан код. Замер 2026-08-22 провалился ровно здесь: агент искал русскими
фразами по английскому коду и не нашёл реализацию, которая в нём была.

Подсказка велит агенту переводить запрос перед поиском, но небольшие сборки
этого не делают. Поэтому перевод выполняется за них: отдельным дешёвым
обращением, ответ которого кэшируется вместе с остальными.
"""

import re

from ducktective.core.llm.ports import (
    LlmClient,
)
from ducktective.core.llm.value_objects import (
    LlmMessage,
    LlmRole,
    ModelRequirements,
)


EXPANSION_PROMPT = (
    "You turn a question about a codebase into the identifiers that would actually appear "
    "in its source. Answer with two to four candidates separated by commas and nothing "
    "else - no explanation, no sentences.\n\n"
    "A candidate is what a programmer would have typed: a field, a class, a function, a "
    "flag, a setting. Prefer the noun being constrained over the behaviour being "
    "described.\n\n"
    "Question: закрытые организации не показываются в списке\n"
    "Answer: is_closed, closed, filter, queryset\n\n"
    "Question: where are permissions checked\n"
    "Answer: has_permission, check_access, permission_required\n"
)

MAX_CANDIDATES = 4
MAX_CANDIDATE_CHARS = 40

CYRILLIC = re.compile(r"[а-яё]", re.IGNORECASE)
WORD_SPLIT = re.compile(r"[,\n;]")


def looks_like_prose(query: str) -> bool:
    """Похож ли запрос на вопрос, а не на имя из кода.

    Кириллица — самый надёжный признак: код английский, и русское слово
    в нём не встретится нигде, кроме комментария. Длинная фраза — второй:
    имя ищут одним словом, поведение описывают несколькими.
    """
    if CYRILLIC.search(query):
        return True
    return len(query.split()) > 2


class QueryExpander:
    """Кандидаты-идентификаторы по вопросу.

    Ошибка не поднимается наверх: расширение — улучшение поиска, а не его
    условие. Не ответила модель — ищем по тому, что спросили.
    """

    def __init__(
        self,
        client: LlmClient,
        *,
        requirements: ModelRequirements,
        limit: int = MAX_CANDIDATES,
    ) -> None:
        self._client = client
        self._requirements = requirements
        self._limit = limit

    async def expand(self, query: str) -> tuple[str, ...]:
        messages = [
            LlmMessage(role=LlmRole.SYSTEM, content=EXPANSION_PROMPT),
            LlmMessage(role=LlmRole.USER, content=f"Question: {query}\nAnswer:"),
        ]
        try:
            response = await self._client.complete(messages, requirements=self._requirements)
        except Exception:
            return ()

        return _candidates(response.content, limit=self._limit)


def _candidates(answer: str, *, limit: int) -> tuple[str, ...]:
    """Разбирает ответ в перечень имён.

    Отбрасывается всё, что похоже на объяснение: имя пишется одним словом,
    а «the field that stores it» — это модель, не выполнившая инструкцию.
    """
    found: list[str] = []
    for piece in WORD_SPLIT.split(answer):
        candidate = piece.strip().strip("`\"'.")
        if not candidate or " " in candidate or len(candidate) > MAX_CANDIDATE_CHARS:
            continue
        if candidate.lower() in {item.lower() for item in found}:
            continue
        found.append(candidate)

    return tuple(found[:limit])
