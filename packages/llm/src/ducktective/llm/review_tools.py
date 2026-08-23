"""Инструменты, которые есть у ревьюера и нет у разговора.

Навигация отвечает про зафиксированную ревизию, а эти два — про сам прогон:
какие ещё файлы в нём изменены и что именно в них изменено. Живут отдельно
от `NavigationToolbox`, потому что источник у них другой: не индекс и не git,
а дифф, который прогон уже держит в руках.
"""

from ducktective.core.diff.value_objects import (
    ChangeType,
)
from ducktective.core.llm.value_objects import (
    ToolCall,
    ToolSpec,
)
from ducktective.core.retrieval.navigation import (
    CodeFragment,
    FragmentRole,
)
from ducktective.core.review.entities import (
    ReviewFile,
    RunDiff,
)
from ducktective.core.review.ports import (
    FindingHistory,
    PastFinding,
)
from ducktective.core.review.value_objects import (
    FeedbackVerdict,
)
from ducktective.core.types import (
    RepositoryId,
)
from ducktective.llm.tools import (
    MAX_TOOL_RESULT_CHARS,
    NavigationToolbox,
    ToolExecutionResult,
    parse_arguments,
)


CHANGE_NAMES = {
    ChangeType.ADDED: "добавлен",
    ChangeType.MODIFIED: "изменён",
    ChangeType.DELETED: "удалён",
    ChangeType.RENAMED: "переименован",
}

SUMMARY_HINT = (
    "Патч любого из них покажет get_file_diff. Прежде чем сказать, что вызывающие "
    "или зависимости не обновлены, посмотрите, не обновлены ли они здесь."
)

GET_DIFF_SUMMARY = ToolSpec(
    name="get_diff_summary",
    description=(
        "List the other files changed in this same review: path, kind of change and line "
        "counts. The change you are reading is often one part of a change spread across "
        "several files, and you only see your own."
    ),
    parameters={"type": "object", "properties": {}},
)

GET_FILE_DIFF = ToolSpec(
    name="get_file_diff",
    description=(
        "Show the patch of another file changed in this same review. Use it before claiming "
        "that callers, imports, manifests or images were not updated: they may well be "
        "updated in the very same change, in a file you cannot see."
    ),
    parameters={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Path of the file, as the summary names it"},
        },
        "required": ["path"],
    },
)

PAST_FINDINGS = ToolSpec(
    name="past_findings",
    description=(
        "Show what was reported about this file in earlier reviews and what the human "
        "said about it: confirmed, false positive, or won't fix. These are verdicts from "
        "the people who own this code."
    ),
    parameters={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "File path, defaults to the one you read"},
        },
    },
)

VERDICT_NAMES = {
    FeedbackVerdict.USEFUL: "подтверждено человеком",
    FeedbackVerdict.FALSE_POSITIVE: "человек назвал ложным срабатыванием",
    FeedbackVerdict.WONTFIX: "человек решил не чинить",
}

HISTORY_HINT = (
    "Это отметки человека на прошлых прогонах, а не запрет. Находка, отклонённая "
    "здесь однажды, скорее всего будет отклонена снова; если ваша про другое или "
    "код с тех пор изменился — сообщите о ней."
)

DIFF_TOOLS = (GET_DIFF_SUMMARY, GET_FILE_DIFF)


class ReviewToolbox:
    """Навигация плюс остальной дифф прогона.

    Инструменты диффа предлагаются, только когда в прогоне есть другие файлы:
    инструмент, отвечающий «файл в прогоне один», тратит и шаг цикла, и место
    в окне, где перечислены инструменты, — то же правило, по которому поиск
    по документу появляется только вместе с документом.
    """

    def __init__(
        self,
        navigation: NavigationToolbox,
        diff: RunDiff,
        *,
        path: str,
        history: FindingHistory | None = None,
        repository_id: RepositoryId | None = None,
        result_chars: int = MAX_TOOL_RESULT_CHARS,
    ) -> None:
        self._navigation = navigation
        self._others = diff.others(path)
        self._diff = diff
        self._path = path
        self._history = history
        self._repository_id = repository_id
        self._result_chars = result_chars

    @property
    def specs(self) -> tuple[ToolSpec, ...]:
        specs = self._navigation.specs
        if self._others:
            specs = (*specs, *DIFF_TOOLS)
        if self._history is not None and self._repository_id is not None:
            specs = (*specs, PAST_FINDINGS)
        return specs

    async def execute(self, call: ToolCall) -> ToolExecutionResult:
        if call.name == PAST_FINDINGS.name:
            return await self._past_findings(call)

        if call.name not in {tool.name for tool in DIFF_TOOLS}:
            return await self._navigation.execute(call)

        if not self._others:
            return ToolExecutionResult("В этом прогоне изменён один файл", is_error=True)

        if call.name == GET_DIFF_SUMMARY.name:
            return ToolExecutionResult(_summary(self._others))

        try:
            arguments = parse_arguments(call.arguments)
        except ValueError as error:
            return ToolExecutionResult(str(error), is_error=True)

        return self._file_diff(str(arguments.get("path", "")))

    async def _past_findings(self, call: ToolCall) -> ToolExecutionResult:
        """Прошлые находки по файлу вместе с вердиктами человека.

        Фрагментов здесь нет: отметка — это мнение о коде, а не код,
        и в проверке доказательств ей делать нечего.
        """
        if self._history is None or self._repository_id is None:
            return ToolExecutionResult("История отметок недоступна", is_error=True)

        try:
            arguments = parse_arguments(call.arguments)
        except ValueError as error:
            return ToolExecutionResult(str(error), is_error=True)

        path = str(arguments.get("path") or self._path)
        found = await self._history.for_file(self._repository_id, path)
        if not found:
            return ToolExecutionResult(f"По файлу {path} размеченных находок ещё нет")

        return ToolExecutionResult(_clip(_history(path, found), self._result_chars))

    def _file_diff(self, path: str) -> ToolExecutionResult:
        """Патч соседнего файла вместе с фрагментом для проверки доказательств.

        Фрагмент едет обратно по той же причине, что и ответ навигации:
        цитата из соседнего патча — законное доказательство, и без него
        находка отбраковывается за то, ради чего инструмент и заведён (D-008).
        """
        found = self._diff.at(path)
        if found is None:
            listed = ", ".join(item.path for item in self._others)
            return ToolExecutionResult(
                f"Файла «{path}» в этом прогоне нет. Изменены: {listed}",
                is_error=True,
            )

        patch = found.to_unified_patch()
        if not patch:
            return ToolExecutionResult(f"У файла {found.path} нет ханков: показывать нечего")

        text = _clip(f"Патч файла {found.path} из этого же прогона\n\n{patch}", self._result_chars)
        return ToolExecutionResult(text, fragments=(_as_fragment(found, patch),))


def _summary(files: tuple[ReviewFile, ...]) -> str:
    lines = [
        f"  {item.path} — {CHANGE_NAMES[item.change_type]}, "
        f"+{item.added_lines} −{item.removed_lines}"
        for item in files
    ]
    listed = "\n".join(lines)
    return f"Ещё файлы этого прогона: {len(files)}\n{listed}\n{SUMMARY_HINT}"


def _history(path: str, findings: list[PastFinding]) -> str:
    lines = [
        f"  строка {item.line_start} · {item.severity.value} · «{item.title}» — "
        f"{VERDICT_NAMES[item.verdict]}" + (f": {item.comment}" if item.comment else "")
        for item in findings
    ]
    listed = "\n".join(lines)
    return f"Что находили в {path} раньше:\n{listed}\n{HISTORY_HINT}"


def _as_fragment(file: ReviewFile, patch: str) -> CodeFragment:
    starts = [hunk.new_start for hunk in file.hunks if hunk.new_lines]
    ends = [hunk.new_start + hunk.new_lines - 1 for hunk in file.hunks if hunk.new_lines]
    return CodeFragment(
        path=file.path,
        start_line=min(starts, default=1),
        end_line=max(ends, default=1),
        text=patch,
        role=FragmentRole.MATCH,
        title=f"{file.path} · патч этого прогона",
    )


def _clip(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text

    remainder = len(text) - limit
    return (
        f"{text[:limit].rstrip()}\n… патч обрезан, ещё {remainder} символов. "
        f"Спросите окружение нужного места через get_file_context."
    )
