import litellm
from litellm.exceptions import (
    APIError,
    RateLimitError,
    Timeout,
)

from ducktective.core.exceptions import (
    LlmInvocationError,
)


RETRYABLE_ERRORS = (RateLimitError, Timeout, APIError)

DEFAULT_BATCH_SIZE = 32

OPENAI_COMPATIBLE_PREFIX = "openai/"


def _qualify(model: str, base_url: str | None) -> str:
    """Дописывает провайдера к имени модели.

    LiteLLM узнаёт провайдера по префиксу имени, а в интерфейсе локального
    сервера модель называется так, как он её показывает: без префикса.
    Свой адрес означает OpenAI-совместимый сервер — LM Studio, vLLM,
    llama.cpp и `/v1` у Ollama говорят одним протоколом.
    """
    if base_url is None or "/" in model:
        return model
    return f"{OPENAI_COMPATIBLE_PREFIX}{model}"


class LiteLlmEmbedder:
    """Локальный эмбеддер через OpenAI-совместимый интерфейс.

    Модель обслуживает Ollama или LM Studio; LiteLLM скрывает разницу.
    Размерность объявляется заранее и сверяется с первым же ответом: колонка
    pgvector фиксирована, и молча положить в неё вектор другой длины нельзя.

    Тексты уходят пачками: на каждый чанк по запросу — это тысячи обращений
    на средний репозиторий.
    """

    def __init__(
        self,
        *,
        model: str,
        dimensions: int,
        base_url: str | None = None,
        api_key: str = "",
        vector_set: str = "",
        batch_size: int = DEFAULT_BATCH_SIZE,
        timeout_seconds: float = 120.0,
    ) -> None:
        self._name = vector_set or model
        self._model = _qualify(model, base_url)
        self._dimensions = dimensions
        self._base_url = base_url
        self._api_key = api_key or "local"
        self._batch_size = batch_size
        self._timeout_seconds = timeout_seconds

    @property
    def name(self) -> str:
        """Имя набора векторов в базе.

        Названо отдельно от модели у сервера: два сервера с одними весами
        пишут в один набор, и смена сервера не требует пересчёта.
        """
        return self._name

    @property
    def dimensions(self) -> int:
        return self._dimensions

    async def embed(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for start in range(0, len(texts), self._batch_size):
            batch = texts[start : start + self._batch_size]
            vectors.extend(await self._embed_batch(batch))
        return vectors

    async def _embed_batch(self, batch: list[str]) -> list[list[float]]:
        try:
            response = await litellm.aembedding(
                model=self._model,
                input=batch,
                api_base=self._base_url,
                api_key=self._api_key,
                timeout=self._timeout_seconds,
            )
        except RETRYABLE_ERRORS as error:
            raise LlmInvocationError(f"Эмбеддер недоступен: {error}") from error
        except Exception as error:
            raise LlmInvocationError(f"Эмбеддер отказал: {error}") from error

        vectors = [item["embedding"] for item in response["data"]]
        self._verify(vectors, expected_count=len(batch))
        return vectors

    def _verify(self, vectors: list[list[float]], *, expected_count: int) -> None:
        if len(vectors) != expected_count:
            raise LlmInvocationError(
                f"Эмбеддер вернул {len(vectors)} векторов вместо {expected_count}"
            )

        wrong = next((len(vector) for vector in vectors if len(vector) != self._dimensions), None)
        if wrong is not None:
            raise LlmInvocationError(
                f"Модель {self._model} вернула вектор размерности {wrong}, "
                f"а индекс рассчитан на {self._dimensions}"
            )
