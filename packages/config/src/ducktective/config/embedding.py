import json
from pathlib import (
    Path,
)

from pydantic import (
    BaseModel,
    Field,
)


DEFAULT_BACKEND_KEY = "default"


class EmbeddingBackend(BaseModel):
    """Сервер, считающий векторы.

    `vector_set` — имя набора векторов в базе. Два сервера с одними и теми же
    весами объявляют один набор и пишут в него вместе; сервер с другой
    моделью обязан назвать другой. Пусто — набор назван именем модели.
    """

    key: str = Field(min_length=1, max_length=64)
    title: str = Field(min_length=1)
    model: str = Field(min_length=1)
    base_url: str = ""
    api_key: str = ""
    vector_set: str = ""
    note: str = ""
    """Чем этот сервер отличается для человека: скорость, где стоит, когда брать."""

    @property
    def vector_set_name(self) -> str:
        return self.vector_set or self.model


def load_embedding_backends(path: Path) -> tuple[EmbeddingBackend, ...]:
    """Читает дополнительные серверы эмбеддингов; отсутствие файла — обычный случай."""
    if not path.is_file():
        return ()

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise ValueError(f"Реестр эмбеддеров не разбирается: {path}") from error

    if not isinstance(payload, list):
        raise ValueError(f"Реестр эмбеддеров должен быть списком: {path}")

    backends = tuple(EmbeddingBackend.model_validate(entry) for entry in payload)
    keys = [backend.key for backend in backends]
    if DEFAULT_BACKEND_KEY in keys or len(set(keys)) != len(keys):
        raise ValueError(
            f"Ключи эмбеддеров должны быть уникальны и не равны «{DEFAULT_BACKEND_KEY}»: {path}"
        )
    return backends
