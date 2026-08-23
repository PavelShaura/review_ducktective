from uuid import (
    uuid4,
)

from ducktective.core.diff.value_objects import (
    ChangeType,
)
from ducktective.core.llm.value_objects import (
    ToolCall,
)
from ducktective.core.retrieval.navigation import (
    NavigationAnswer,
    NavigationSource,
    ReferenceRelation,
)
from ducktective.core.review.entities import (
    ReviewFile,
    ReviewHunk,
    RunDiff,
)
from ducktective.core.types import (
    ReviewFileId,
    ReviewHunkId,
)
from ducktective.llm.review_tools import (
    ReviewToolbox,
)
from ducktective.llm.tools import (
    NavigationToolbox,
)


class SilentNavigator:
    """Навигатор, которому в этих тестах отвечать нечем."""

    source = NavigationSource.INDEX

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
        return NavigationAnswer(source=self.source)

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


def review_file(
    path: str,
    *,
    added: str = "tablib==4.1",
    added_lines: int = 1,
    removed_lines: int = 1,
) -> ReviewFile:
    return ReviewFile(
        id=ReviewFileId(uuid4()),
        path=path,
        previous_path=None,
        change_type=ChangeType.MODIFIED,
        language=None,
        added_lines=added_lines,
        removed_lines=removed_lines,
        hunks=[
            ReviewHunk(
                id=ReviewHunkId(uuid4()),
                old_start=10,
                old_lines=2,
                new_start=10,
                new_lines=2,
                header="",
                patch_text=f"@@ -10,2 +10,2 @@\n-tablib==3.9\n+{added}\n",
            )
        ],
    )


def toolbox(*paths: str, current: str = "manifest.txt") -> ReviewToolbox:
    diff = RunDiff(tuple(review_file(path) for path in paths))
    return ReviewToolbox(NavigationToolbox(SilentNavigator()), diff, path=current)


def call(name: str, arguments: str = "{}") -> ToolCall:
    return ToolCall(id="call_1", name=name, arguments=arguments)


async def test_summary_lists_the_other_files_of_the_run() -> None:
    box = toolbox("manifest.txt", "images/build.conf", current="manifest.txt")

    result = await box.execute(call("get_diff_summary"))

    assert "images/build.conf" in result.text
    assert "manifest.txt" not in result.text
    assert not result.is_error


async def test_patch_of_a_neighbour_is_shown_with_its_lines() -> None:
    """Правка редко живёт в одном файле, а ревьюер видит только свой."""
    box = toolbox("manifest.txt", "images/build.conf", current="manifest.txt")

    result = await box.execute(call("get_file_diff", '{"path": "images/build.conf"}'))

    assert "tablib==4.1" in result.text
    assert [fragment.path for fragment in result.fragments] == ["images/build.conf"]
    assert result.fragments[0].start_line == 10


async def test_neighbour_patch_can_be_named_by_the_tail_of_its_path() -> None:
    box = toolbox("manifest.txt", "images/build.conf", current="manifest.txt")

    result = await box.execute(call("get_file_diff", '{"path": "build.conf"}'))

    assert not result.is_error
    assert "tablib==4.1" in result.text


async def test_unknown_path_answers_with_what_the_run_does_contain() -> None:
    """Тупик стоит шага цикла, перечень изменённого — следующего запроса."""
    box = toolbox("manifest.txt", "images/build.conf", current="manifest.txt")

    result = await box.execute(call("get_file_diff", '{"path": "nowhere.py"}'))

    assert result.is_error
    assert "images/build.conf" in result.text


async def test_diff_tools_are_offered_when_the_run_has_other_files() -> None:
    box = toolbox("manifest.txt", "images/build.conf", current="manifest.txt")

    offered = [spec.name for spec in box.specs]

    assert "get_diff_summary" in offered
    assert "get_file_diff" in offered


async def test_single_file_run_does_not_offer_them() -> None:
    """Инструмент, отвечающий «файл один», тратит шаг цикла и место в окне."""
    box = toolbox("manifest.txt", current="manifest.txt")

    offered = [spec.name for spec in box.specs]

    assert "get_diff_summary" not in offered
    assert "get_file_diff" not in offered


async def test_navigation_calls_still_reach_the_navigator() -> None:
    box = toolbox("manifest.txt", "images/build.conf", current="manifest.txt")

    result = await box.execute(call("search_code", '{"query": "weasyprint"}'))

    assert not result.is_error
    assert "Ничего не нашлось" in result.text
