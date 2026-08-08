from collections.abc import (
    Collection,
)

from ducktective.core.review.entities import (
    ReviewFile,
)
from ducktective.core.review.reviewers import (
    ReviewMode,
)


AGENTIC_PATCH_CHARS_LIMIT = 12000
"""Насколько крупный файл ещё имеет смысл читать агентно.

Считается от окна модели, а не от вкуса. При 16 000 системный промпт
и зарезервированный ответ забирают около трети, остальное делят между собой
патч и всё, что модель себе напросит. Патч в двенадцать тысяч символов —
это примерно четыре тысячи токенов, и после него на результаты инструментов
остаётся столько, что цикл упрётся в потолок на втором вызове.

Крупный файл не остаётся без ревью: он читается одним проходом, где всё
место достаётся ему одному.
"""


def plan_file_review(
    file: ReviewFile,
    *,
    available: Collection[ReviewMode] = tuple(ReviewMode),
    patch_chars_limit: int = AGENTIC_PATCH_CHARS_LIMIT,
) -> ReviewMode | None:
    """Решает, как читать этот файл.

    Узел планирования остаётся ограничителем стоимости (D-018), но ограничивает
    он теперь не число проходов на файл, а режим: ревьюер один, и выбор идёт
    между диалогом с инструментами и одним выстрелом.

    Правило одно и оно про окно, а не про содержимое файла. Признаки, по которым
    прежде звали специалистов — `subprocess` в добавленных строках, запрос
    внутри цикла, — больше ничего не решают: единственный ревьюер читает файл
    целиком, и сузить его внимание перечнем маркеров значит вернуть ту же
    четверть картины, ради ухода от которой специализации и убраны (D-022).

    `None` возвращается только тогда, когда читать нечем вовсе: без ревьюеров
    прогон обязан молчать, а не делать вид, что файл проверен.
    """
    if not available:
        return None

    if ReviewMode.AGENTIC in available and _fits_agentic_window(file, patch_chars_limit):
        return ReviewMode.AGENTIC

    if ReviewMode.SINGLE_PASS in available:
        return ReviewMode.SINGLE_PASS

    return next(iter(available))


def _fits_agentic_window(file: ReviewFile, patch_chars_limit: int) -> bool:
    return sum(len(hunk.patch_text) for hunk in file.hunks) <= patch_chars_limit
