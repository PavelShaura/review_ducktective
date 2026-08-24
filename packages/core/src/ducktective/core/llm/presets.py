from dataclasses import (
    dataclass,
)

from ducktective.core.code_repository.value_objects import (
    ModelTrust,
)


@dataclass(frozen=True, kw_only=True)
class ModelPreset:
    """Известный провайдер с заполненными полями.

    Нужен ради одного: бесплатные тиры перебирают. Заполнять адрес, окно
    и признак инструментов руками на каждую пробу — способ не пробовать
    вовсе.

    Ключ ни в одном пресете не зашит: провайдеров, отвечающих без ключа,
    среди пригодных нет, поэтому у каждого назван адрес, где ключ выдают
    бесплатно (D-029).
    """

    key: str
    title: str
    model: str
    provider: str = ""
    base_url: str = ""
    trust: ModelTrust = ModelTrust.TRAINING_REMOTE
    supports_tools: bool = True
    context_window: int = 0
    signup_url: str = ""
    pricing: str = ""
    """Чем платят за этот доступ — словом, а не догадкой по описанию.

    Разница между бесплатным тиром, подпиской и оплатой по токенам решает
    выбор быстрее любого другого признака, и прятать её в конец примечания
    значит заставлять читать всё подряд.
    """

    note: str = ""


MODEL_PRESETS: tuple[ModelPreset, ...] = (
    ModelPreset(
        key="opencode-zen",
        pricing="бесплатно",
        title="OpenCode Zen",
        model="openai/big-pickle",
        provider="openai",
        base_url="https://opencode.ai/zen/v1",
        context_window=128000,
        signup_url="https://opencode.ai/auth",
        note="Бесплатные модели шлюза. Ключ выдаётся без платёжных данных; "
        "часть моделей на период бесплатности учится на запросах",
    ),
    ModelPreset(
        key="opencode-go",
        pricing="подписка, от $10 в месяц",
        title="OpenCode Go (подписка)",
        model="openai/kimi-k3",
        provider="openai",
        base_url="https://opencode.ai/zen/go/v1",
        trust=ModelTrust.PRIVATE_REMOTE,
        context_window=128000,
        signup_url="https://opencode.ai/auth",
        note="Подписка на открытые модели. Лимит долларовый, а не по числу "
        "обращений, — для разговора это важнее: цикл тратит по запросу на шаг. "
        "У большинства моделей нулевое хранение и запрет обучения; исключения "
        "названы в их описании у провайдера",
    ),
    ModelPreset(
        key="openrouter-free",
        pricing="бесплатно",
        title="OpenRouter, бесплатный маршрут",
        model="openrouter/openai/gpt-oss-120b:free",
        provider="openrouter",
        context_window=131072,
        signup_url="https://openrouter.ai/keys",
        note="Около 50 запросов в сутки без депозита. Агентный прогон на десяти "
        "файлах в этот лимит не помещается — годится для одного диффа",
    ),
    ModelPreset(
        key="groq",
        pricing="бесплатный тир",
        title="Groq",
        model="groq/llama-3.3-70b-versatile",
        provider="groq",
        context_window=131072,
        signup_url="https://console.groq.com/keys",
        note="Быстрые ответы, лимит по токенам в сутки",
    ),
    ModelPreset(
        key="gemini",
        pricing="бесплатный тир",
        title="Google AI Studio",
        model="gemini/gemini-2.5-flash",
        provider="gemini",
        context_window=1000000,
        signup_url="https://aistudio.google.com/apikey",
        note="Большое окно и щедрый бесплатный тир; запросы используются для улучшения моделей",
    ),
    ModelPreset(
        key="cerebras",
        pricing="бесплатный тир",
        title="Cerebras",
        model="cerebras/qwen-3-coder-480b",
        provider="cerebras",
        context_window=131072,
        signup_url="https://cloud.cerebras.ai",
        note="Бесплатный тир с суточным лимитом токенов",
    ),
    ModelPreset(
        key="anthropic",
        pricing="по токенам",
        title="Anthropic",
        model="anthropic/claude-sonnet-5",
        provider="anthropic",
        trust=ModelTrust.PRIVATE_REMOTE,
        context_window=200000,
        signup_url="https://console.anthropic.com/settings/keys",
        note="Платный провайдер: запросы не используются для обучения",
    ),
    ModelPreset(
        key="compatible",
        pricing="свой сервер",
        title="Свой OpenAI-совместимый сервер",
        model="openai/",
        provider="openai",
        trust=ModelTrust.PRIVATE_REMOTE,
        note="Шлюз или сервер в своей сети: укажите адрес с суффиксом /v1",
    ),
)


def find_preset(key: str) -> ModelPreset | None:
    for preset in MODEL_PRESETS:
        if preset.key == key:
            return preset
    return None
