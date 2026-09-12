from dataclasses import (
    dataclass,
)

import httpx
import litellm

from ducktective.llm.headers import (
    provider_headers,
)
from ducktective.llm.router import (
    ModelChoice,
)


MODEL_LIST_LIMIT = 200
PROBE_TIMEOUT_SECONDS = 20.0


@dataclass(frozen=True, kw_only=True)
class ProbeResult:
    """Что удалось выяснить о модели до того, как её сохранили.

    Проверка нужна ровно потому, что иначе первым испытанием ключа станет
    настоящий вопрос: человек введёт его, задаст вопрос и через минуту
    получит отказ, не понимая, дело в ключе, адресе или имени модели.
    """

    is_reachable: bool
    detail: str
    models: tuple[str, ...] = ()


async def probe_model(choice: ModelChoice) -> ProbeResult:
    """Спрашивает провайдера, отвечает ли он на этот ключ.

    Сначала пробуется перечень моделей: у OpenAI-совместимых серверов он
    отдаётся одним дешёвым запросом и заодно избавляет человека от угадывания
    идентификатора. Не вышло — делается самый короткий из возможных вызовов:
    он тратит одно обращение, зато отвечает на вопрос точно.
    """
    if choice.api_base:
        listed = await _list_models(choice)
        if listed is not None:
            return ProbeResult(
                is_reachable=True,
                detail=f"Провайдер ответил, моделей доступно: {len(listed)}",
                models=listed,
            )

    return await _minimal_call(choice)


async def _list_models(choice: ModelChoice) -> tuple[str, ...] | None:
    url = choice.api_base.rstrip("/") + "/models" if choice.api_base else ""
    headers = {"Authorization": f"Bearer {choice.api_key}"} if choice.api_key else {}

    try:
        async with httpx.AsyncClient(timeout=PROBE_TIMEOUT_SECONDS) as client:
            response = await client.get(url, headers=headers)
            response.raise_for_status()
            payload = response.json()
    except (httpx.HTTPError, ValueError):
        return None

    entries = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(entries, list):
        return None

    names = [
        str(entry["id"])
        for entry in entries
        if isinstance(entry, dict) and isinstance(entry.get("id"), str)
    ]
    return tuple(sorted(names)[:MODEL_LIST_LIMIT])


async def _minimal_call(choice: ModelChoice) -> ProbeResult:
    """Самый дешёвый вызов, какой признаётся ответом: один токен."""
    payload = {
        "model": choice.model,
        "messages": [{"role": "user", "content": "ping"}],
        "max_tokens": 1,
        "timeout": PROBE_TIMEOUT_SECONDS,
        "num_retries": 0,
    }
    if choice.api_base:
        payload["api_base"] = choice.api_base
    if choice.api_key:
        payload["api_key"] = choice.api_key
    headers = provider_headers(choice)
    if headers:
        payload["extra_headers"] = headers

    try:
        await litellm.acompletion(**payload)
    except Exception as error:
        return ProbeResult(is_reachable=False, detail=_short(error))

    return ProbeResult(is_reachable=True, detail="Модель ответила")


def _short(error: Exception) -> str:
    """Первая строка ошибки: остальное — трассировка библиотеки."""
    text = str(error).strip().splitlines()
    return text[0][:300] if text else type(error).__name__
