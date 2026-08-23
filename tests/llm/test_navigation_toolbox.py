from ducktective.core.llm.value_objects import (
    ToolCall,
)
from ducktective.core.retrieval.navigation import (
    CodeFragment,
    FragmentRole,
    NavigationAnswer,
    NavigationSource,
    ReferenceRelation,
)
from ducktective.llm.tools import (
    NavigationToolbox,
)


class RecordingNavigator:
    """Навигатор, запоминающий, о чём его спросили."""

    source = NavigationSource.INDEX

    def __init__(self) -> None:
        self.relations: list[ReferenceRelation] = []

    async def search_code(self, query: str, *, limit: int = 10) -> NavigationAnswer:
        return NavigationAnswer(source=self.source)

    async def get_definition(self, name: str, *, limit: int = 5) -> NavigationAnswer:
        return NavigationAnswer(source=self.source)

    async def find_callers(self, name: str, *, limit: int = 20) -> NavigationAnswer:
        return NavigationAnswer(source=self.source)

    async def find_references(
        self,
        name: str,
        *,
        relation: ReferenceRelation = ReferenceRelation.ANY,
        limit: int = 20,
    ) -> NavigationAnswer:
        self.relations.append(relation)
        return NavigationAnswer(
            source=self.source,
            fragments=(
                CodeFragment(
                    path="app/packs.py",
                    start_line=10,
                    end_line=12,
                    text="class BranchPack(BasePack):",
                    role=FragmentRole.SUBCLASS,
                    title="app.packs.BranchPack · class",
                ),
            ),
        )

    async def get_file_context(
        self,
        path: str,
        *,
        start_line: int,
        end_line: int,
        limit: int = 10,
    ) -> NavigationAnswer:
        return NavigationAnswer(source=self.source)

    async def list_files(self, pattern: str, *, limit: int = 40) -> NavigationAnswer:
        return NavigationAnswer(source=self.source)


def call(arguments: str) -> ToolCall:
    return ToolCall(id="call_1", name="find_references", arguments=arguments)


async def test_relation_reaches_the_navigator() -> None:
    navigator = RecordingNavigator()

    await NavigationToolbox(navigator).execute(
        call('{"name": "BasePack", "relation": "subclasses"}')
    )

    assert navigator.relations == [ReferenceRelation.SUBCLASSES]


async def test_unknown_relation_is_read_as_any() -> None:
    """Препирательство о написании стоит шага цикла, а их пять."""
    navigator = RecordingNavigator()

    await NavigationToolbox(navigator).execute(
        call('{"name": "BasePack", "relation": "inheritance"}')
    )

    assert navigator.relations == [ReferenceRelation.ANY]


async def test_missing_relation_is_read_as_any() -> None:
    navigator = RecordingNavigator()

    await NavigationToolbox(navigator).execute(call('{"name": "BasePack"}'))

    assert navigator.relations == [ReferenceRelation.ANY]


async def test_result_names_the_kind_of_reference() -> None:
    """Иначе наследник читается как вызывающий, а это разные последствия."""
    result = await NavigationToolbox(RecordingNavigator()).execute(
        call('{"name": "BasePack", "relation": "subclasses"}')
    )

    assert "Наследует" in result.text
    assert not result.is_error


async def test_the_tool_is_offered_to_the_model() -> None:
    toolbox = NavigationToolbox(RecordingNavigator())

    assert "find_references" in [spec.name for spec in toolbox.specs]
