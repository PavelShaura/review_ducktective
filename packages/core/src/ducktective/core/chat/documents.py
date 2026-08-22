"""Отбор кусков приложенного документа под вопрос.

Документ не едет в подсказку целиком (D-025): страница на двадцать килобайт
занимает сорок процентов окна локальной модели, и на найденный код места
не остаётся. Из него достаётся то, что относится к вопросу.

Отбор лексический и здесь, в домене: это правило о том, что считать
относящимся к делу, а не работа с хранилищем. Векторов у документа нет
и не нужно, пока не доказано, что слов не хватает: у страницы требований
сотни абзацев против сорока тысяч фрагментов кодовой базы.
"""

import html
import re
from dataclasses import (
    dataclass,
)


PARAGRAPH_BREAK = re.compile(r"\n\s*\n")
WORD = re.compile(r"[\w/.-]{3,}", re.UNICODE)

SCRIPT_OR_STYLE = re.compile(r"<(script|style)\b.*?</\1>", re.DOTALL | re.IGNORECASE)
BLOCK_TAG = re.compile(
    r"</?(p|div|br|li|ul|ol|tr|td|th|table|h[1-6]|section|article|pre)\b[^>]*>",
    re.IGNORECASE,
)
ANY_TAG = re.compile(r"<[^>]+>")
EXTRA_BLANK_LINES = re.compile(r"\n{3,}")

STEM_PREFIX = 6
"""По скольким первым буквам слова считаются одним.

Документ пишут по-русски, и вопрос тоже: «как выбирается филиал» против
«пользователь выбирает филиал» — совпадений по целым словам ноль, хотя
речь об одном. Полноценная лемматизация тянет словарь на десятки мегабайт;
усечение до общей части ловит склонения и спряжения тем же движением
и ошибается там, где слова и правда близки: «печать» и «печатается».
"""

HEADING_CHARS = 90
"""Короче этого абзац считается заголовком и приходит вместе со следующим."""

DEFAULT_PASSAGES = 4
MAX_PASSAGE_CHARS = 1200
"""Сколько знаков берётся от одного абзаца.

Абзац требований бывает страницей: таблица, длинный список условий. Целиком
он вытеснит и соседей, и код, а первых полутора тысяч знаков хватает,
чтобы понять, о чём место, и спросить точнее.
"""


@dataclass(frozen=True, kw_only=True)
class Passage:
    """Кусок документа вместе с его местом в нём."""

    number: int
    text: str


def plain_text(raw: str) -> str:
    """Снимает разметку, оставляя абзацы.

    Выгрузка из Confluence приходит страницей HTML, и теги в подсказке
    занимают место, ничего не объясняя. Блочные теги превращаются в пустую
    строку, потому что деление на абзацы — единственное, что из разметки
    действительно нужно: по нему потом отбираются куски.

    Разбор здесь простой и это осознанно: документ — не код, идеальное
    извлечение из произвольного HTML не окупается, а пустые строки на месте
    заголовков и абзацев переживают любую верстку.
    """
    if "<" not in raw:
        return raw

    without_hidden = SCRIPT_OR_STYLE.sub(" ", raw)
    paragraphed = BLOCK_TAG.sub("\n\n", without_hidden)
    stripped = ANY_TAG.sub("", paragraphed)
    unescaped = html.unescape(stripped)
    return EXTRA_BLANK_LINES.sub("\n\n", unescaped).strip()


def split_passages(text: str) -> list[str]:
    """Делит документ по пустым строкам.

    Абзац — единица смысла в требованиях: заголовок с текстом под ним,
    пункт списка, ячейка таблицы. Деление по строкам порвало бы их,
    а по размеру — склеило чужое.
    """
    return [passage.strip() for passage in PARAGRAPH_BREAK.split(text) if passage.strip()]


def select_passages(
    text: str,
    query: str,
    *,
    limit: int = DEFAULT_PASSAGES,
    passage_chars: int = MAX_PASSAGE_CHARS,
) -> list[Passage]:
    """Куски документа, относящиеся к вопросу, сверху — самые близкие.

    Близость считается по редким словам: слово, встречающееся в половине
    абзацев, ничего не отличает, а встретившееся дважды — отличает сильно.
    Поэтому вклад слова тем больше, чем реже оно в самом документе.

    Пустой ответ честнее выдуманного: вопрос, ни одним словом не задевший
    документ, не должен получать первый попавшийся абзац как «относящийся».
    """
    passages = split_passages(text)
    if not passages:
        return []

    wanted = _words(query)
    if not wanted:
        return []

    presence = _presence(passages, wanted)
    scored = [
        (_score(passage, wanted, presence, len(passages)), number, passage)
        for number, passage in enumerate(passages, start=1)
    ]
    found = sorted(
        (item for item in scored if item[0] > 0),
        key=lambda item: (-item[0], item[1]),
    )

    return [
        Passage(
            number=number,
            text=_clipped(_with_body(passages, number, passage), passage_chars),
        )
        for _, number, passage in found[:limit]
    ]


def _with_body(passages: list[str], number: int, passage: str) -> str:
    """Дописывает к заголовку то, что под ним.

    В требованиях заголовок — отдельный абзац из одной строки, и по словам
    вопроса он совпадает лучше тела: «Требование 3.2. Печать справки» против
    «Справка печатается в PDF». Возвращённый один, он не отвечает ни на что —
    человек узнаёт, что такой пункт есть, но не что в нём написано.
    """
    if len(passage) > HEADING_CHARS or number >= len(passages):
        return passage
    return f"{passage}\n{passages[number]}"


def _words(text: str) -> set[str]:
    """Слова текста, приведённые к общей части: склонения считаются одним."""
    return {_stem(match.group()) for match in WORD.finditer(text)}


def _stem(word: str) -> str:
    lowered = word.lower()
    return lowered[:STEM_PREFIX] if len(lowered) > STEM_PREFIX else lowered


def _presence(passages: list[str], wanted: set[str]) -> dict[str, int]:
    counts = dict.fromkeys(wanted, 0)
    for passage in passages:
        for word in _words(passage) & wanted:
            counts[word] += 1
    return counts


def _score(passage: str, wanted: set[str], presence: dict[str, int], total: int) -> float:
    matched = _words(passage) & wanted
    if not matched:
        return 0.0
    return sum(total / (presence[word] or total) for word in matched)


def _clipped(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return f"{text[:limit].rstrip()}…"
