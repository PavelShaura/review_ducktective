from ducktective.application.indexing.embedders import (
    EmbedderCatalogue,
)
from ducktective.config.settings import (
    Settings,
)
from ducktective.llm.embedder import (
    LiteLlmEmbedder,
)
from ducktective.llm.factory import (
    build_embedders,
)


def embedder_catalogue(settings: Settings) -> EmbedderCatalogue:
    return EmbedderCatalogue.from_backends(settings.embedding_backends())


def embedders_of(settings: Settings) -> dict[str, LiteLlmEmbedder]:
    return build_embedders(settings.embedding_backends(), dimensions=settings.embedding_dimensions)
