from ducktective.core.llm.value_objects import (
    LlmMessage,
    LlmResponse,
    LlmUsage,
    ModelRequirements,
    ToolCall,
)
from ducktective.core.retrieval.navigation import (
    CodeFragment,
    NavigationAnswer,
)
from ducktective.llm.query_expansion import (
    QueryExpander,
    looks_like_prose,
)
from ducktective.llm.tools import (
    NavigationToolbox,
)
from tests.fakes import (
    StubNavigator,
)


class SearchingNavigator(StubNavigator):
    """Навигатор, помнящий, по чему его просили искать."""

    def __init__(self) -> None:
        self.queries: list[str] = []

    async def search_code(self, query: str, *, limit: int = 10) -> NavigationAnswer:
        self.queries.append(query)
        return NavigationAnswer(
            source=self.source,
            fragments=(
                CodeFragment(
                    path=f"app/{query}.py",
                    start_line=1,
                    end_line=2,
                    text=f"# {query}",
                ),
            ),
        )


class AnsweringClient:
    """Клиент, отвечающий заранее заданным текстом."""

    def __init__(self, content: str) -> None:
        self.content = content
        self.calls = 0

    async def complete(self, messages: list[LlmMessage], **kwargs: object) -> LlmResponse:
        self.calls += 1
        return LlmResponse(
            content=self.content,
            model="fake",
            provider="fake",
            usage=LlmUsage(input_tokens=10, output_tokens=5),
        )


class FailingClient:
    async def complete(self, messages: list[LlmMessage], **kwargs: object) -> LlmResponse:
        raise RuntimeError("модель недоступна")


def expander(client: object) -> QueryExpander:
    return QueryExpander(client, requirements=ModelRequirements())  # type: ignore[arg-type]


def call(query: str) -> ToolCall:
    return ToolCall(id="call_1", name="search_code", arguments=f'{{"query": "{query}"}}')


def test_a_russian_question_is_prose() -> None:
    """Код английский: русское слово не встретится в нём нигде."""
    assert looks_like_prose("где проверяются права")


def test_an_identifier_is_not_prose() -> None:
    assert not looks_like_prose("AccessChecker")
    assert not looks_like_prose("/catalog_branch_select")


async def test_a_question_becomes_identifiers() -> None:
    candidates = await expander(AnsweringClient("is_closed, closed, filter")).expand(
        "закрытые организации не показываются"
    )

    assert candidates == ("is_closed", "closed", "filter")


async def test_an_explanation_instead_of_names_is_discarded() -> None:
    """Имя пишется одним словом; фраза — это невыполненная инструкция."""
    candidates = await expander(AnsweringClient("the field that stores it")).expand("вопрос")

    assert candidates == ()


async def test_a_failing_model_leaves_the_search_alone() -> None:
    """Расширение — улучшение поиска, а не его условие."""
    candidates = await expander(FailingClient()).expand("вопрос")

    assert candidates == ()


async def test_search_goes_by_the_candidates_and_by_the_question() -> None:
    navigator = SearchingNavigator()
    toolbox = NavigationToolbox(
        navigator,
        expander=expander(AnsweringClient("is_closed, filter")),
    )

    await toolbox.execute(call("закрытые организации"))

    assert navigator.queries[:2] == ["is_closed", "filter"]
    assert "закрытые организации" in navigator.queries


async def test_the_answer_says_what_was_actually_searched() -> None:
    """Молча подменённый запрос — это выдача, которую нельзя объяснить."""
    toolbox = NavigationToolbox(
        SearchingNavigator(),
        expander=expander(AnsweringClient("is_closed, filter")),
    )

    result = await toolbox.execute(call("закрытые организации"))

    assert "is_closed, filter" in result.text


async def test_an_identifier_query_is_not_expanded() -> None:
    navigator = SearchingNavigator()
    client = AnsweringClient("is_closed")
    toolbox = NavigationToolbox(navigator, expander=expander(client))

    await toolbox.execute(call("AccessChecker"))

    assert navigator.queries == ["AccessChecker"]
    assert client.calls == 0
