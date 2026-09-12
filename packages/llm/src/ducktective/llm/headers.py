import uuid
from typing import (
    Any,
)


USER_AGENT = "review-ducktective/0.1"
OPENCODE_HOST = "opencode.ai"
OPENCODE_SESSION_HEADER = "x-opencode-session"


def provider_headers(choice: Any, session_key: str = "") -> dict[str, str]:
    """Заголовки, без которых провайдер отказывает.

    OpenCode Go принимает только трафик кодирующих агентов: агент обязан
    назваться своим `User-Agent` и слать в каждом запросе стабильный на
    разговор `x-opencode-session`, по которому шлюз маршрутизирует и кэширует
    промпт между шагами. Запрос без него отклоняется до модели. Разовому
    обращению — пробе, вопросу без разговора — ключ придумывается на месте:
    провайдеру важно его наличие, а не история.

    Остальным провайдерам ничего не добавляется: лишний заголовок у чужого
    сервера — повод для отказа, а не безобидная вежливость.
    """
    api_base = getattr(choice, "api_base", None) or ""
    if OPENCODE_HOST not in api_base:
        return {}
    return {
        "User-Agent": USER_AGENT,
        OPENCODE_SESSION_HEADER: session_key or uuid.uuid4().hex,
    }
