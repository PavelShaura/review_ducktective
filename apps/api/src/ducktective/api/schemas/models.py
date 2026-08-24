from datetime import (
    datetime,
)
from uuid import (
    UUID,
)

from pydantic import (
    BaseModel,
    Field,
)

from ducktective.core.code_repository.value_objects import (
    ModelTrust,
)
from ducktective.core.llm.presets import (
    ModelPreset,
)
from ducktective.core.llm.provider_connection import (
    ProviderConnection,
)


class ProviderConnectionResponse(BaseModel):
    """Подключение организации. Ключ не отдаётся — только признак, что он задан."""

    id: UUID
    name: str
    default_model: str
    models: list[str]
    catalogue_refreshed_at: datetime | None
    provider: str
    base_url: str
    trust: ModelTrust
    supports_tools: bool
    context_window: int
    note: str
    is_enabled: bool
    has_api_key: bool
    created_at: datetime

    @classmethod
    def from_domain(cls, connection: ProviderConnection) -> "ProviderConnectionResponse":
        return cls(
            id=connection.id,
            name=connection.name,
            default_model=connection.default_model,
            models=list(connection.models),
            catalogue_refreshed_at=connection.catalogue_refreshed_at,
            provider=connection.provider,
            base_url=connection.base_url,
            trust=connection.trust,
            supports_tools=connection.supports_tools,
            context_window=connection.context_window,
            note=connection.note,
            is_enabled=connection.is_enabled,
            has_api_key=bool(connection.encrypted_api_key),
            created_at=connection.created_at,
        )


class AddConnectionRequest(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    api_key: str = ""
    default_model: str = ""
    catalogue: list[str] = Field(default_factory=list)
    provider: str = ""
    base_url: str = ""
    trust: ModelTrust = ModelTrust.TRAINING_REMOTE
    supports_tools: bool = True
    context_window: int = 0
    note: str = ""


class UpdateConnectionRequest(BaseModel):
    """Правка подключения. Пустой ключ значит «оставить прежний», а не «стереть»."""

    default_model: str | None = None
    api_key: str | None = None
    base_url: str | None = None
    trust: ModelTrust | None = None
    supports_tools: bool | None = None
    context_window: int | None = None
    note: str | None = None
    is_enabled: bool | None = None


class ModelPresetResponse(BaseModel):
    """Известный провайдер с заполненными полями и адресом, где взять ключ."""

    key: str
    title: str
    model: str
    provider: str
    base_url: str
    trust: ModelTrust
    supports_tools: bool
    context_window: int
    signup_url: str
    pricing: str
    note: str

    @classmethod
    def from_domain(cls, preset: ModelPreset) -> "ModelPresetResponse":
        return cls(
            key=preset.key,
            title=preset.title,
            model=preset.model,
            provider=preset.provider,
            base_url=preset.base_url,
            trust=preset.trust,
            supports_tools=preset.supports_tools,
            context_window=preset.context_window,
            signup_url=preset.signup_url,
            pricing=preset.pricing,
            note=preset.note,
        )


class ProbeConnectionRequest(BaseModel):
    """Проверка до сохранения: отвечает ли провайдер на этот ключ."""

    model: str = Field(min_length=1, max_length=255)
    api_key: str = ""
    provider: str = ""
    base_url: str = ""


class ProbeConnectionResponse(BaseModel):
    is_reachable: bool
    detail: str
    models: list[str] = Field(default_factory=list)
