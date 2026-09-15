from ducktective.core.review.value_objects import (
    ReviewLanguage,
)


TRACE: dict[str, dict[ReviewLanguage, str]] = {
    "asking_model": {
        ReviewLanguage.RU: "Спрашиваю модель, обращение {attempt}",
        ReviewLanguage.EN: "Asking the model, call {attempt}",
    },
    "answer_cut": {
        ReviewLanguage.RU: "Ответ модели оборвался на лимите — прошу повторить вызов",
        ReviewLanguage.EN: "The model's answer was cut at the limit — asking for the call again",
    },
    "window_full": {
        ReviewLanguage.RU: "Диалог заполнил окно модели: около {tokens} токенов из {window}",
        ReviewLanguage.EN: "The dialogue filled the model window: about {tokens} tokens of {window}",
    },
    "call_ceiling": {
        ReviewLanguage.RU: "Достигнут потолок обращений: {limit}",
        ReviewLanguage.EN: "Reached the call ceiling: {limit}",
    },
    "fallback_no_tools": {
        ReviewLanguage.RU: "инструменты навигации недоступны",
        ReviewLanguage.EN: "navigation tools are unavailable",
    },
    "fallback_window": {
        ReviewLanguage.RU: "диалог не поместился в окно модели: {error}",
        ReviewLanguage.EN: "the dialogue did not fit the model window: {error}",
    },
    "fallback_unparsed": {
        ReviewLanguage.RU: "итог расследования не разобрался: {error}",
        ReviewLanguage.EN: "the investigation result could not be parsed: {error}",
    },
    "file_clean": {
        ReviewLanguage.RU: "Файл прочитан, замечаний нет",
        ReviewLanguage.EN: "File read, no findings",
    },
    "file_findings": {
        ReviewLanguage.RU: "Файл прочитан, замечаний: {count}",
        ReviewLanguage.EN: "File read, findings: {count}",
    },
    "finding_line": {
        ReviewLanguage.RU: "· строка {line} [{severity}] {title}",
        ReviewLanguage.EN: "· line {line} [{severity}] {title}",
    },
    "context_of": {
        ReviewLanguage.RU: "Окружение {position} из {total}: {path}",
        ReviewLanguage.EN: "Context {position} of {total}: {path}",
    },
    "plan_nothing": {
        ReviewLanguage.RU: "Читать нечего: в диффе нет файлов для ревью",
        ReviewLanguage.EN: "Nothing to read: the diff has no files to review",
    },
    "plan_agentic": {
        ReviewLanguage.RU: "План: расследую {agentic} файл(ов) с инструментами",
        ReviewLanguage.EN: "Plan: investigating {agentic} file(s) with tools",
    },
    "plan_plain": {
        ReviewLanguage.RU: "План: читаю {plain} файл(ов) одним проходом",
        ReviewLanguage.EN: "Plan: reading {plain} file(s) in a single pass",
    },
    "plan_mixed": {
        ReviewLanguage.RU: "План: {agentic} файл(ов) с инструментами, {plain} одним проходом",
        ReviewLanguage.EN: "Plan: {agentic} file(s) with tools, {plain} in a single pass",
    },
    "reading_agentic": {
        ReviewLanguage.RU: "Расследую",
        ReviewLanguage.EN: "Investigating",
    },
    "reading_plain": {
        ReviewLanguage.RU: "Читаю одним проходом",
        ReviewLanguage.EN: "Reading in a single pass",
    },
    "verify_clean": {
        ReviewLanguage.RU: "Проверяю доказательства: подтверждено {confirmed}, отброшенных нет",
        ReviewLanguage.EN: "Checking the evidence: {confirmed} confirmed, nothing dropped",
    },
    "verify_dropped": {
        ReviewLanguage.RU: "Проверяю доказательства: подтверждено {confirmed}, отброшено — {named}",
        ReviewLanguage.EN: "Checking the evidence: {confirmed} confirmed, dropped — {named}",
    },
    "reason_outside_diff": {ReviewLanguage.RU: "вне диффа", ReviewLanguage.EN: "outside the diff"},
    "reason_no_evidence": {ReviewLanguage.RU: "без цитаты", ReviewLanguage.EN: "without a quote"},
    "reason_unproven": {
        ReviewLanguage.RU: "без проверки чужого кода",
        ReviewLanguage.EN: "foreign code not checked",
    },
    "reason_duplicates": {ReviewLanguage.RU: "дубли", ReviewLanguage.EN: "duplicates"},
}
"""Фразы ленты расследования на языках, которые умеет интерфейс.

Лента — для человека: он читает её на языке, на котором завёл дело.
Здесь только то, что видит человек. Результаты инструментов, которые
читает модель, сюда не входят: их язык — часть подсказки, и менять его
значит менять поведение ревьюера, а это делается с eval-прогоном.
"""


def trace(language: ReviewLanguage, key: str, **values: object) -> str:
    """Фраза ленты на языке прогона; неизвестный ключ — ошибка программиста."""
    return TRACE[key][language].format(**values)
