import re
from collections.abc import (
    AsyncIterator,
    Sequence,
)
from functools import (
    cache,
)
from pathlib import (
    Path,
)

from ducktective.core.chat.entities import (
    ChatMessage,
)
from ducktective.core.chat.ports import (
    ChatRequest,
)
from ducktective.core.chat.value_objects import (
    ChatEvent,
    ChatEventKind,
    ChatRole,
    ChatUsage,
    ToolInvocation,
)
from ducktective.core.exceptions import (
    LlmContextOverflowError,
    LlmInvocationError,
)
from ducktective.core.llm.ports import (
    StreamingLlmClient,
)
from ducktective.core.llm.value_objects import (
    LlmMessage,
    LlmResponse,
    LlmRole,
    ModelRequirements,
    ToolCall,
)
from ducktective.llm.query_expansion import (
    QueryExpander,
)
from ducktective.llm.tools import (
    NavigationToolbox,
    render_for_model,
)


PROMPTS_DIRECTORY = Path(__file__).parent / "prompts"
CHAT_PROMPT_FILE = "chat.md"

DEFAULT_MAX_STEPS = 6
"""Сколько раз агент обращается к модели на один вопрос.

Считается по окну, а не по терпению: каждый результат инструмента остаётся
в диалоге до конца ответа, и на седьмом обращении разбирать будет уже негде.
Вопрос при этом требует больше ходов, чем файл ревью, — сперва найти место,
потом прочитать определение, потом посмотреть вызывающих.
"""

DEFAULT_HISTORY_LIMIT = 8
"""Сколько прошлых реплик уезжает в модель.

История копится, а окно нет: разговор из тридцати реплик не поместится
целиком ни в какую локальную модель. Берётся хвост — то, о чём говорят
сейчас; ссылка на сказанное час назад теряется, и это осознанная цена
простого правила.

Реплики инструментов в историю не попадают вовсе: найденный фрагмент нужен,
пока агент составляет ответ, а в следующем вопросе он занимает место,
которого стоит новый поиск.
"""

INDEX_REVISION_NOTE = (
    "Ответ описывает ревизию {revision}, на которой собран индекс: "
    "незакоммиченных правок и коммитов свежее в нём нет."
)

NO_TOOLS_NOTE = (
    "Отвечаю по тому, что нашлось поиском по вашему вопросу: уточнить выдачу было нечем."
)

OVERFLOW_NOTE = (
    "Разговор перестал помещаться в окно модели — отвечаю по одному поиску, "
    "без уточнений. Начните новый разговор, чтобы вернуть расследование."
)

DOCUMENT_NOTE = (
    "К разговору приложен документ «{name}» — могу искать и в нём. "
    "Пока он приложен, разговор идёт только через локальную модель."
)

DOCUMENT_HEAD_CHARS = 700
"""Сколько начала документа видно модели без вызова инструмента.

Хватает, чтобы понять, что за документ и о чём он: заголовок, первый абзац,
начало оглавления. Больше — значит платить окном за то, что и так достанется
поиском, когда понадобится.
"""

PRESET_SEARCH_LIMIT = 6

TOOL_CALL_ARTEFACT = re.compile(r"<\|?\s*tool_call|<tool_call", re.IGNORECASE)
"""След вызова, напечатанного текстом вместо протокола.

Небольшие сборки на последнем шаге, где инструменты сняты, иногда печатают
вызов разметкой прямо в ответ. Человеку это читается как часть объяснения.
"""

FINAL_INSTRUCTION = (
    "This is your last turn: the tools are gone. Answer now with what you have already "
    "learned - the document, the fragments you read, the places you found - and say plainly "
    "which part of the question you could not check. A partial answer with locations beats "
    "«I ran out of steps», which tells the person nothing they can use."
)

OUT_OF_STEPS = (
    "Мне не хватило шагов, чтобы дойти до ответа. Спросите точнее — назовите файл, "
    "класс или поле, — и я посмотрю прицельно."
)

TOOL_RESULT_CHARS = 2600
"""Сколько от ответа инструмента видит агент разговора.

Больше, чем у ревьюера: там окно делится с патчем файла, здесь — только
с историей и найденным. При окне 16 384 системный промпт и резерв под ответ
забирают около трети, и на четыре-пять результатов остаётся по две с половиной
тысячи знаков — столько, чтобы фрагмент доезжал с телом функции, а не с одной
сигнатурой.
"""

DEAD_END_MESSAGE = (
    "You are about to answer that you did not find something, that you need to narrow the "
    "search, or to ask the person to clarify. Do the lookup yourself instead: the tools are "
    "still in front of you and the person cannot search for you. Search for a concrete marker "
    "- an import, a class name, a field, a filter, a setting - not for the sentence you were "
    "asked. A requirement written in Russian prose appears nowhere in English code; the field "
    "it constrains appears in every place that enforces it. If the next search comes back "
    "empty too, say so plainly and stop."
)

DEAD_END_NOTE = "Ответ упёрся в тупик — прошу поискать по конкретному имени, а не по понятию"
"""Как переспрос выглядит в ленте.

Модели уходит английский текст, человеку показывается русская строка:
это реплика конвейера, а не мысль модели, и выдавать её за мысль значит
приписывать модели наши слова.
"""

DEAD_END_MARKERS = (
    "не вижу никакого документа",
    "не вижу документ",
    "предоставьте документ",
    "приложите документ",
    "не нашёл",
    "не нашел",
    "не смог найти",
    "не смогла найти",
    "не найдено",
    "не удалось найти",
    "не удалось обнаружить",
    "нет прямого упоминания",
    "потребуется искать",
    "потребуется найти",
    "нужно искать",
    "мне потребуется",
    "сузить поиск",
    "уточните",
    "did not find",
    "could not find",
    "i would need",
    "i need to search",
    "narrow the search",
    "please clarify",
    "no direct mention",
)
"""Слова, которыми ответ сам признаётся, что работа не доделана.

Список по словам ответа, а не по выдаче инструментов: пустой поиск —
это ещё не тупик, тупиком его делает вывод «раз не нашлось, значит нет».
Живой пример: на вопрос про фреймворк бэкенда агент поискал «web framework»,
ничего не понял и закончил словами «потребуется искать импорты» — при том
что импорт django лежал в 4949 чанках из 38826.
"""


class AgenticChatAgent:
    """Отвечает на вопрос о коде, добывая сведения инструментами.

    От `AgenticCodeReviewer` отличается входом, а не устройством: там патч,
    здесь вопрос и история. Инструменты, обрезка каждого результата, предел
    шагов и упор в окно — те же и по той же причине (D-024).

    Ответ идёт потоком. Текст, сказанный перед вызовом инструмента, — это
    рассуждение по пути, и вызов его закрывает: в ленте видно, о чём агент
    подумал, прежде чем что-то посмотреть, но итогом это не притворяется.

    Откат один и ведёт на преднабор: модели без инструментов фрагменты
    находятся заранее поиском по самому вопросу. Такой ответ хуже — уточнить
    выдачу он не может, — но он есть, а отказ отвечать не помог бы никому.
    """

    def __init__(
        self,
        llm_client: StreamingLlmClient,
        *,
        fallback: "PresetChatAgent",
        max_steps: int = DEFAULT_MAX_STEPS,
        history_limit: int = DEFAULT_HISTORY_LIMIT,
    ) -> None:
        self._llm_client = llm_client
        self._fallback = fallback
        self._max_steps = max_steps
        self._history_limit = history_limit

    async def answer(self, request: ChatRequest) -> AsyncIterator[ChatEvent]:
        if request.index_revision:
            yield ChatEvent(
                kind=ChatEventKind.NOTE,
                text=INDEX_REVISION_NOTE.format(revision=request.index_revision[:12]),
            )

        if request.document is not None:
            yield ChatEvent(
                kind=ChatEventKind.NOTE,
                text=DOCUMENT_NOTE.format(name=request.document.name),
            )

        try:
            async for event in self._investigate(request):
                yield event
        except LlmContextOverflowError:
            yield ChatEvent(kind=ChatEventKind.NOTE, text=OVERFLOW_NOTE)
            async for event in self._fallback.answer(request):
                if event.kind is not ChatEventKind.NOTE:
                    yield event
        except LlmInvocationError as error:
            yield ChatEvent(kind=ChatEventKind.FAILURE, text=str(error))

    async def _investigate(self, request: ChatRequest) -> AsyncIterator[ChatEvent]:
        if request.navigator is None:
            return

        toolbox = NavigationToolbox(
            request.navigator,
            result_chars=TOOL_RESULT_CHARS,
            document=request.document,
            expander=QueryExpander(
                self._llm_client,
                requirements=request.requirements,
            ),
        )
        messages = self._opening(request)
        requirements = _with_tool_calling(request.requirements)
        spent = ChatUsage()
        is_nudged = False

        for step in range(1, self._max_steps + 1):
            is_last = step == self._max_steps
            if is_last:
                messages.append(LlmMessage(role=LlmRole.USER, content=FINAL_INSTRUCTION))

            said: list[str] = []
            response: LlmResponse | None = None

            async for piece in self._llm_client.stream(
                messages,
                requirements=requirements,
                tools=None if is_last else toolbox.specs,
            ):
                if piece.response is not None:
                    response = piece.response
                    break

                said.append(piece.text)
                yield ChatEvent(kind=ChatEventKind.TOKEN, text=piece.text)

            if response is None:
                raise LlmInvocationError("Модель закрыла поток, не ответив")

            spoken = "".join(said) or response.content
            spent = spent.plus(_usage_of(response))

            if not response.has_tool_calls:
                spoken = clean_answer(spoken) or (OUT_OF_STEPS if is_last else spoken)

                if not is_last and not is_nudged and _is_dead_end(spoken):
                    is_nudged = True
                    messages.extend(
                        [
                            LlmMessage(role=LlmRole.ASSISTANT, content=spoken),
                            LlmMessage(role=LlmRole.USER, content=DEAD_END_MESSAGE),
                        ]
                    )
                    yield ChatEvent(kind=ChatEventKind.NOTE, text=DEAD_END_NOTE)
                    continue

                yield ChatEvent(
                    kind=ChatEventKind.ANSWER,
                    text=spoken,
                    model=response.model,
                    usage=spent,
                )
                return

            messages.append(
                LlmMessage(
                    role=LlmRole.ASSISTANT,
                    content=spoken,
                    tool_calls=response.tool_calls,
                )
            )

            for call in response.tool_calls:
                invocation = _to_invocation(call)
                yield ChatEvent(kind=ChatEventKind.TOOL_CALL, tool=invocation)

                result = await toolbox.execute(call)
                yield ChatEvent(
                    kind=ChatEventKind.TOOL_RESULT,
                    tool=invocation,
                    text=result.text,
                )
                messages.append(
                    LlmMessage(
                        role=LlmRole.TOOL,
                        content=result.text,
                        tool_call_id=call.id,
                    )
                )

    def _opening(self, request: ChatRequest) -> list[LlmMessage]:
        return _opening(request, history_limit=self._history_limit)


class PresetChatAgent:
    """Отвечает по тому, что нашлось поиском по самому вопросу.

    Нужен там, где цикл не работает: модель не умеет вызывать инструменты
    или диалог перестал помещаться в окно. Уточнить выдачу такой ответ
    не может — что нашлось по первому запросу, тем и отвечает, — но это
    всё же ответ по коду проекта, а не по общим представлениям о том,
    как такое обычно пишут.
    """

    def __init__(
        self,
        llm_client: StreamingLlmClient,
        *,
        fragments_limit: int = PRESET_SEARCH_LIMIT,
        history_limit: int = DEFAULT_HISTORY_LIMIT,
    ) -> None:
        self._llm_client = llm_client
        self._fragments_limit = fragments_limit
        self._history_limit = history_limit

    async def answer(self, request: ChatRequest) -> AsyncIterator[ChatEvent]:
        yield ChatEvent(kind=ChatEventKind.NOTE, text=NO_TOOLS_NOTE)

        messages = _opening(request, history_limit=self._history_limit)
        if request.navigator is not None:
            found = await request.navigator.search_code(
                request.question,
                limit=self._fragments_limit,
            )
            messages[-1] = LlmMessage(
                role=LlmRole.USER,
                content=f"{request.question}\n\n{render_for_model(found)}",
            )

        said: list[str] = []
        response: LlmResponse | None = None

        try:
            async for piece in self._llm_client.stream(
                messages,
                requirements=request.requirements,
            ):
                if piece.response is not None:
                    response = piece.response
                    break

                said.append(piece.text)
                yield ChatEvent(kind=ChatEventKind.TOKEN, text=piece.text)
        except LlmInvocationError as error:
            yield ChatEvent(kind=ChatEventKind.FAILURE, text=str(error))
            return

        if response is None:
            yield ChatEvent(kind=ChatEventKind.FAILURE, text="Модель закрыла поток, не ответив")
            return

        yield ChatEvent(
            kind=ChatEventKind.ANSWER,
            text="".join(said) or response.content,
            model=response.model,
            usage=_usage_of(response),
        )


@cache
def system_prompt() -> str:
    return (PROMPTS_DIRECTORY / CHAT_PROMPT_FILE).read_text(encoding="utf-8")


def _opening(request: ChatRequest, *, history_limit: int) -> list[LlmMessage]:
    return [
        LlmMessage(role=LlmRole.SYSTEM, content=system_prompt()),
        *_document_notice(request),
        *(
            LlmMessage(role=_role_of(message), content=message.content)
            for message in _recent(request.history, limit=history_limit)
        ),
        LlmMessage(role=LlmRole.USER, content=request.question),
    ]


def _document_notice(request: ChatRequest) -> list[LlmMessage]:
    """Говорит модели, что документ уже здесь, и показывает его начало.

    Инструмента мало: на вопрос «что это за документ» небольшая сборка
    отвечает «предоставьте документ», не заглянув в инструмент вовсе —
    привычка чат-бота сильнее перечня возможностей. Имя, размер и первые
    строки снимают вопрос до всякого вызова, а сам вызов остаётся за тем,
    что в документе дальше.
    """
    if request.document is None:
        return []

    head = request.document.text[:DOCUMENT_HEAD_CHARS].strip()
    return [
        LlmMessage(
            role=LlmRole.SYSTEM,
            content=(
                f"A document is attached to this conversation and is available to you right "
                f"now through `search_document`. Never say that you cannot see it or ask for "
                f"it to be provided.\n"
                f"Name: {request.document.name}\n"
                f"Size: {request.document.size} characters\n"
                f"It begins with:\n{head}"
            ),
        )
    ]


def clean_answer(answer: str) -> str:
    """Убирает из ответа попытку вызвать инструмент текстом.

    На последнем шаге инструменты сняты, а модель всё ещё хочет искать —
    и небольшие сборки печатают вызов разметкой прямо в ответ:
    `<|tool_call>call:search_code{query:...}`. Показывать это человеку
    нельзя: он читает служебный мусор как часть объяснения.

    Отрезается хвост, а не строка целиком: до разметки в ответе обычно
    сказано что-то полезное, и терять его вместе с мусором незачем.
    """
    cleaned = TOOL_CALL_ARTEFACT.split(answer, maxsplit=1)[0]
    return cleaned.strip()


def _is_dead_end(answer: str) -> bool:
    """Признаётся ли ответ, что до конца не дошёл.

    Переспрашивается один раз и только пока шаги есть: цена — одно обращение
    к модели, а без него разговор кончается фразой «мне потребуется поискать
    импорты» вместо самого поиска.

    Ложное срабатывание здесь дёшево и даже полезно: ответ «в коде такого
    нет» тоже стоит проверить вторым запросом, прежде чем утверждать
    отсутствие.
    """
    lowered = answer.lower()
    return any(marker in lowered for marker in DEAD_END_MARKERS)


def _recent(history: Sequence[ChatMessage], *, limit: int) -> list[ChatMessage]:
    spoken = [
        message
        for message in history
        if message.role is not ChatRole.TOOL and message.content.strip()
    ]
    return spoken[-limit:]


def _role_of(message: ChatMessage) -> LlmRole:
    return LlmRole.USER if message.role is ChatRole.USER else LlmRole.ASSISTANT


def _to_invocation(call: ToolCall) -> ToolInvocation:
    return ToolInvocation(call_id=call.id, name=call.name, arguments=call.arguments)


def _usage_of(response: LlmResponse) -> ChatUsage:
    return ChatUsage(
        input_tokens=response.usage.input_tokens,
        output_tokens=response.usage.output_tokens,
    )


def _with_tool_calling(requirements: ModelRequirements) -> ModelRequirements:
    """Требование к модели на время разговора.

    Окно просится большее, чем одноразовому проходу: диалог копит и историю,
    и результаты инструментов, и, в отличие от ревью, не кончается вместе
    с файлом.
    """
    return ModelRequirements(
        needs_deep_reasoning=requirements.needs_deep_reasoning,
        needs_tool_calling=True,
        min_context_tokens=max(requirements.min_context_tokens, 16384),
        cloud_allowed=requirements.cloud_allowed,
        max_output_tokens=requirements.max_output_tokens,
        temperature=requirements.temperature,
    )
