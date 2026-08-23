import json
from pathlib import (
    Path,
)

from pydantic import (
    BaseModel,
    Field,
)

from ducktective.core.code_repository.value_objects import (
    ModelTrust,
)


class RemoteModel(BaseModel):
    """Удалённая модель из реестра установки.

    Ключ хранится не здесь, а в переменной окружения, имя которой названо
    полем `api_key_env`: файл реестра лежит в репозитории установки рядом
    с настройками и попадает в резервные копии, а секретам там не место.

    Уровень доверия обязателен и по умолчанию самый строгий из удалённых:
    провайдер, про которого не сказано обратного, считается обучающимся
    на запросах. Ошибиться в эту сторону дешевле (D-028).
    """

    name: str = Field(min_length=1, max_length=64)
    model: str = Field(min_length=1)
    provider: str = ""
    base_url: str = ""
    api_key_env: str = ""
    trust: ModelTrust = ModelTrust.TRAINING_REMOTE
    supports_tools: bool = True
    context_window: int = 0
    note: str = ""
    """Чем эта модель отличается для человека: лимиты, цена, оговорки."""


def load_remote_models(path: Path) -> tuple[RemoteModel, ...]:
    """Читает реестр моделей, если он есть.

    Отсутствие файла — обычный случай: установка с одной локальной моделью
    самодостаточна, и требовать от неё пустой список значило бы усложнять
    первый запуск.
    """
    if not path.is_file():
        return ()

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise ValueError(f"Реестр моделей не разбирается: {path}") from error

    if not isinstance(payload, list):
        raise ValueError(f"Реестр моделей должен быть списком: {path}")

    return tuple(RemoteModel.model_validate(entry) for entry in payload)


LEGACY_MODEL_NAME = "cloud"


def legacy_remote_model(*, model: str, context_window: int, api_key_env: str) -> RemoteModel:
    """Одна удалённая модель, описанная переменными окружения.

    Совместимость с установками, поднятыми до реестра: там облачная модель
    задавалась парой «модель и ключ», и молча перестать её читать значило бы
    сломать работающее. Уровень доверия у неё `private_remote` — прежняя
    настройка означала платного провайдера, а не бесплатный тир.
    """
    return RemoteModel(
        name=LEGACY_MODEL_NAME,
        model=model,
        provider=model.split("/", 1)[0] if "/" in model else "",
        api_key_env=api_key_env,
        trust=ModelTrust.PRIVATE_REMOTE,
        context_window=context_window,
    )
